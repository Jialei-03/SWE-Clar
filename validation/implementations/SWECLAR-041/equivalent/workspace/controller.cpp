#include "controller.hpp"
#include <charconv>
#include <sstream>
#include <vector>

namespace {
bool integer(const std::string& text, int64_t& value) {
  const char* end = text.data() + text.size();
  const auto result = std::from_chars(text.data(), end, value, 10);
  return result.ec == std::errc{} && result.ptr == end;
}

std::string invalid_command() {
  return "{\"ok\":false,\"error\":\"invalid_command\"}";
}

std::string accepted() { return "{\"ok\":true}"; }
}  // namespace

Controller::Controller(Hal& hal) : hal_(hal) {
  update_mode();
  // The initial high GPIO record is deliberately emitted before the first
  // registration beacon, matching the public wire-order rule.
  hal_.advertise(0);
}

void Controller::set_led(bool level, uint32_t tick) {
  if (level == level_) return;
  level_ = level;
  hal_.gpio(tick, level);
}

Controller::LedMode Controller::desired_mode() const {
  if (!network_) return LedMode::network_down;  // fast blink
  if (!hal_.bus_ready()) return LedMode::bus_pending;  // slow blink
  return LedMode::ready;  // solid high
}

void Controller::update_mode() {
  const LedMode next_mode = desired_mode();
  if (next_mode == mode_) return;

  mode_ = next_mode;
  switch (mode_) {
    case LedMode::network_down:
      half_period_ = 100;
      break;
    case LedMode::bus_pending:
      half_period_ = 500;
      break;
    case LedMode::ready:
      half_period_ = 0;
      break;
    case LedMode::uninitialized:
      // desired_mode() never returns this sentinel; retaining a safe solid
      // output makes the invariant explicit if a new mode is added later.
      half_period_ = 0;
      break;
  }

  set_led(true, now_);
  next_edge_ = half_period_ == 0
                   ? UINT64_MAX
                   : static_cast<uint64_t>(now_) + half_period_;
}

void Controller::link_changed() { update_mode(); }

void Controller::advance(uint32_t target) {
  // Both schedules are absolute virtual timestamps.  Selecting the GPIO
  // event first on equality gives the required GPIO-before-beacon ordering.
  while (true) {
    const uint64_t edge = next_edge_;
    const uint64_t beacon = next_advert_;
    const uint64_t event = edge < beacon ? edge : beacon;
    if (event > target) break;

    if (edge <= beacon) {
      set_led(!level_, static_cast<uint32_t>(edge));
      next_edge_ = edge + half_period_;
    } else {
      hal_.advertise(static_cast<uint32_t>(beacon));
      next_advert_ = beacon + 1000;
    }
  }
  now_ = target;
}

void Controller::health(int rssi, int channel, int bandwidth) {
  // A sample is a one-shot operation.  Hal's outbox is only used for this
  // current, acknowledged connection and is discarded if that connection
  // closes.
  if (network_ && hal_.bus_ready()) hal_.publish(now_, rssi, channel, bandwidth);
}

std::string Controller::status() const {
  std::ostringstream out;
  out << "{\"ok\":true,\"time\":" << now_
      << ",\"network\":" << (network_ ? "true" : "false")
      << ",\"broker\":" << (hal_.bus_ready() ? "true" : "false")
      << ",\"pending\":" << (hal_.bus_pending() ? "true" : "false")
      << ",\"registered\":" << (registered_ ? "true" : "false")
      << ",\"led_level\":" << (level_ ? 1 : 0)
      << ",\"registration_port\":" << hal_.registration_port() << "}";
  return out.str();
}

std::string Controller::command(const std::string& line) {
  // main() enforces this limit while consuming the serial stream as well;
  // keeping the check here makes the command operation safe on its own.
  if (line.size() > 256) return invalid_command();

  std::istringstream input(line);
  std::vector<std::string> parts;
  std::string part;
  while (input >> part) parts.push_back(part);
  if (parts.empty()) return invalid_command();

  const std::string& name = parts[0];
  if (name == "status" && parts.size() == 1) return status();
  if (name == "quit" && parts.size() == 1) {
    quitting_ = true;
    return accepted();
  }
  if (name == "registered" && parts.size() == 1) {
    if (!registered_) {
      registered_ = true;
      next_advert_ = UINT64_MAX;
      hal_.stop_registration();
    }
    return accepted();
  }

  if ((name == "network" || name == "broker") && parts.size() == 2
      && (parts[1] == "0" || parts[1] == "1")) {
    const bool enabled = parts[1] == "1";

    if (name == "network") {
      const bool changed = enabled != network_;
      network_ = enabled;
      if (!enabled) hal_.close_bus();
      if (changed) update_mode();
      return accepted();
    }

    if (enabled && !network_) return "{\"ok\":false,\"error\":\"network_down\"}";
    if (enabled) {
      // open_bus itself is defensive, but this guard documents and enforces
      // that repeated requests do not create a second connection.
      if (!hal_.bus_ready() && !hal_.bus_pending()) hal_.open_bus();
    } else {
      hal_.close_bus();
    }
    update_mode();
    return accepted();
  }

  if (name == "advance" && parts.size() == 2) {
    int64_t target = 0;
    if (!integer(parts[1], target) || target < static_cast<int64_t>(now_)
        || target > 86400000 || target - static_cast<int64_t>(now_) > 10000) {
      return invalid_command();
    }
    advance(static_cast<uint32_t>(target));
    return accepted();
  }

  if (name == "health" && parts.size() == 4) {
    int64_t rssi = 0;
    int64_t channel = 0;
    int64_t bandwidth = 0;
    if (!integer(parts[1], rssi) || !integer(parts[2], channel) || !integer(parts[3], bandwidth)
        || rssi < -127 || rssi > 0 || channel < 1 || channel > 14
        || (bandwidth != 20 && bandwidth != 40 && bandwidth != 80)) {
      return invalid_command();
    }
    health(static_cast<int>(rssi), static_cast<int>(channel), static_cast<int>(bandwidth));
    return accepted();
  }

  return invalid_command();
}
