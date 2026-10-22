#pragma once
#include "hal.hpp"
#include <cstdint>
#include <string>
#include <vector>

class Controller {
 public:
  explicit Controller(Hal& hal);
  std::string command(const std::string& line);
  void link_changed();
  bool quitting() const { return quitting_; }
 private:
  Hal& hal_;
  uint32_t now_ = 0;
  uint64_t next_edge_ = UINT64_MAX, next_advert_ = 1000;
  uint32_t half_period_ = 0;
  int mode_ = -1;
  bool network_ = false, registered_ = false, level_ = false, quitting_ = false;
  void update_mode();
  void set_led(bool level, uint32_t tick);
  void advance(uint32_t target);
  void health(int rssi, int channel, int bandwidth);
  std::string status() const;
};
