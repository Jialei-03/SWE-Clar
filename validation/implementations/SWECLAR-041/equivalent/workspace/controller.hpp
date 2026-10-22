#pragma once
#include "hal.hpp"
#include <cstdint>
#include <string>

class Controller {
 public:
  explicit Controller(Hal& hal);
  std::string command(const std::string& line);
  void link_changed();
  bool quitting() const { return quitting_; }

 private:
  enum class LedMode : uint8_t { uninitialized, network_down, bus_pending, ready };

  Hal& hal_;
  uint32_t now_ = 0;
  uint64_t next_edge_ = UINT64_MAX;
  uint64_t next_advert_ = 1000;
  uint32_t half_period_ = 0;
  LedMode mode_ = LedMode::uninitialized;
  bool network_ = false;
  bool registered_ = false;
  bool level_ = false;
  bool quitting_ = false;

  LedMode desired_mode() const;
  void update_mode();
  void set_led(bool level, uint32_t tick);
  void advance(uint32_t target);
  void health(int rssi, int channel, int bandwidth);
  std::string status() const;
};
