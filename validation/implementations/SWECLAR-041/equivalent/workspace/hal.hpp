#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

class Hal {
 public:
  Hal(int board_port, int bus_port);
  ~Hal();

  int registration_fd() const { return registration_fd_; }
  int registration_port() const { return registration_port_; }
  int bus_fd() const { return bus_fd_; }
  bool bus_ready() const { return ready_; }
  bool bus_pending() const { return bus_fd_ >= 0 && !ready_; }
  short bus_events() const;

  void service_registration();
  void stop_registration();
  void gpio(uint32_t tick, bool level);
  void advertise(uint32_t tick);
  void open_bus();
  void close_bus();
  void service_bus(short events);
  void publish(uint32_t tick, int rssi, int channel, int bandwidth);

 private:
  int board_fd_ = -1;
  int board_port_;
  int bus_port_;
  int registration_fd_ = -1;
  int registration_port_ = 0;
  int bus_fd_ = -1;
  bool connecting_ = false;
  bool ready_ = false;
  bool hello_sent_ = false;
  std::string handshake_;
  std::vector<uint8_t> outbox_;

  void board_send(const uint8_t* bytes, std::size_t length);
  void queue_hello();
  bool flush_bus_output();
};
