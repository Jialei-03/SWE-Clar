#include "controller.hpp"
#include <algorithm>
#include <charconv>
#include <sstream>

namespace {
bool integer(const std::string& text, int64_t& value) {
  const char* end = text.data() + text.size();
  auto result = std::from_chars(text.data(), end, value);
  return result.ec == std::errc{} && result.ptr == end;
}
std::string error() { return "{\"ok\":false,\"error\":\"invalid_command\"}"; }
}
Controller::Controller(Hal& hal) : hal_(hal) { update_mode(); hal_.advertise(0); }
void Controller::set_led(bool level, uint32_t tick) {
  if (level != level_) { level_ = level; hal_.gpio(tick, level); }
}
void Controller::update_mode() {
  // Provisional power indicator; implement the agreed connectivity timing policy.
  set_led(true, now_);
  next_edge_ = UINT64_MAX;
}
void Controller::link_changed() { update_mode(); }
void Controller::advance(uint32_t target) {
  while (std::min(next_edge_, next_advert_) <= target) {
    uint32_t event_time = static_cast<uint32_t>(std::min(next_edge_, next_advert_));
    if (next_edge_ == event_time) { set_led(!level_, event_time); next_edge_ += half_period_; }
    if (next_advert_ == event_time) { hal_.advertise(event_time); next_advert_ += 1000; }
  }
  now_ = target;
}
void Controller::health(int rssi, int channel, int bandwidth) {
  // The transport encoder exists; complete publication eligibility and delivery.
  (void)rssi; (void)channel; (void)bandwidth;
}
std::string Controller::status() const {
  std::ostringstream out;
  out << "{\"ok\":true,\"time\":" << now_ << ",\"network\":" << (network_ ? "true" : "false")
      << ",\"broker\":" << (hal_.bus_ready() ? "true" : "false") << ",\"pending\":" << (hal_.bus_pending() ? "true" : "false")
      << ",\"registered\":" << (registered_ ? "true" : "false") << ",\"led_level\":" << (level_ ? 1 : 0)
      << ",\"registration_port\":" << hal_.registration_port() << "}";
  return out.str();
}
std::string Controller::command(const std::string& line) {
  std::istringstream input(line); std::vector<std::string> parts; std::string part;
  while (input >> part) parts.push_back(part);
  if (parts.empty()) return error();
  const auto& name = parts[0];
  if (name == "status" && parts.size() == 1) return status();
  if (name == "quit" && parts.size() == 1) { quitting_ = true; return "{\"ok\":true}"; }
  if (name == "registered" && parts.size() == 1) {
    registered_ = true; next_advert_ = UINT64_MAX; hal_.stop_registration(); return "{\"ok\":true}";
  }
  if ((name == "network" || name == "broker") && parts.size() == 2 && (parts[1] == "0" || parts[1] == "1")) {
    bool enabled = parts[1] == "1";
    if (name == "network") { network_ = enabled; if (!enabled) hal_.close_bus(); }
    else { if (enabled && !network_) return "{\"ok\":false,\"error\":\"network_down\"}"; if (enabled) hal_.open_bus(); else hal_.close_bus(); }
    update_mode(); return "{\"ok\":true}";
  }
  if (name == "advance" && parts.size() == 2) {
    int64_t target;
    if (!integer(parts[1], target) || target < now_ || target > 86400000 || target - now_ > 10000) return error();
    advance(static_cast<uint32_t>(target)); return "{\"ok\":true}";
  }
  if (name == "health" && parts.size() == 4) {
    int64_t rssi, channel, bandwidth;
    if (!integer(parts[1], rssi) || !integer(parts[2], channel) || !integer(parts[3], bandwidth)
        || rssi < -127 || rssi > 0 || channel < 1 || channel > 14 || (bandwidth != 20 && bandwidth != 40 && bandwidth != 80)) return error();
    health(rssi, channel, bandwidth); return "{\"ok\":true}";
  }
  return "{\"ok\":true}";
}
