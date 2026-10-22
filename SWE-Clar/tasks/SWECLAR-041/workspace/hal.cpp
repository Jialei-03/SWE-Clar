#include "hal.hpp"
#include <arpa/inet.h>
#include <cerrno>
#include <fcntl.h>
#include <poll.h>
#include <stdexcept>
#include <sys/socket.h>
#include <unistd.h>

namespace {
sockaddr_in address(int port) {
  sockaddr_in result{}; result.sin_family = AF_INET; result.sin_port = htons(port);
  result.sin_addr.s_addr = htonl(INADDR_LOOPBACK); return result;
}
void nonblocking(int fd) {
  if (fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK) < 0) throw std::runtime_error("fcntl");
}
void u32(std::vector<uint8_t>& bytes, uint32_t value) {
  for (int shift : {24, 16, 8, 0}) bytes.push_back(static_cast<uint8_t>(value >> shift));
}
}
Hal::Hal(int board_port, int bus_port) : board_port_(board_port), bus_port_(bus_port) {
  board_fd_ = socket(AF_INET, SOCK_DGRAM, 0);
  registration_fd_ = socket(AF_INET, SOCK_STREAM, 0);
  if (board_fd_ < 0 || registration_fd_ < 0) throw std::runtime_error("socket");
  auto local = address(0);
  if (bind(registration_fd_, reinterpret_cast<sockaddr*>(&local), sizeof(local)) < 0 || listen(registration_fd_, 8) < 0)
    throw std::runtime_error("registration listener");
  socklen_t length = sizeof(local);
  if (getsockname(registration_fd_, reinterpret_cast<sockaddr*>(&local), &length) < 0) throw std::runtime_error("getsockname");
  registration_port_ = ntohs(local.sin_port); nonblocking(registration_fd_);
}
Hal::~Hal() { stop_registration(); close_bus(); if (board_fd_ >= 0) close(board_fd_); }
void Hal::stop_registration() { if (registration_fd_ >= 0) close(registration_fd_); registration_fd_ = -1; }
void Hal::service_registration() {
  while (registration_fd_ >= 0) {
    int client = accept(registration_fd_, nullptr, nullptr);
    if (client < 0) return;
    send(client, "SETUP\n", 6, MSG_NOSIGNAL); close(client);
  }
}
void Hal::board_send(const std::vector<uint8_t>& bytes) {
  auto destination = address(board_port_);
  auto n = sendto(board_fd_, bytes.data(), bytes.size(), 0, reinterpret_cast<sockaddr*>(&destination), sizeof(destination));
  if (n != static_cast<ssize_t>(bytes.size())) throw std::runtime_error("virtual board output");
}
void Hal::gpio(uint32_t tick, bool level) { std::vector<uint8_t> b{1}; u32(b, tick); b.push_back(level ? 1 : 0); board_send(b); }
void Hal::advertise(uint32_t tick) { std::vector<uint8_t> b{2}; u32(b, tick); board_send(b); }
void Hal::open_bus() {
  if (bus_fd_ >= 0) return;
  bus_fd_ = socket(AF_INET, SOCK_STREAM, 0);
  if (bus_fd_ < 0) return;
  nonblocking(bus_fd_); auto destination = address(bus_port_);
  int result = connect(bus_fd_, reinterpret_cast<sockaddr*>(&destination), sizeof(destination));
  if (result < 0 && errno != EINPROGRESS) { close_bus(); return; }
  connecting_ = true; ready_ = false; handshake_.clear(); outbox_.clear();
}
void Hal::close_bus() {
  if (bus_fd_ >= 0) close(bus_fd_);
  bus_fd_ = -1; connecting_ = ready_ = false; handshake_.clear(); outbox_.clear();
}
short Hal::bus_events() const { return POLLIN | ((connecting_ || !outbox_.empty()) ? POLLOUT : 0); }
void Hal::service_bus(short events) {
  if (bus_fd_ < 0) return;
  if (events & (POLLERR | POLLHUP | POLLNVAL)) { close_bus(); return; }
  if (connecting_ && (events & POLLOUT)) {
    int error = 0; socklen_t size = sizeof(error);
    if (getsockopt(bus_fd_, SOL_SOCKET, SO_ERROR, &error, &size) < 0 || error) { close_bus(); return; }
    connecting_ = false; outbox_ = {'H','B','0','1'};
  }
  if (!outbox_.empty() && (events & POLLOUT)) {
    ssize_t n = send(bus_fd_, outbox_.data(), outbox_.size(), MSG_NOSIGNAL);
    if (n > 0) outbox_.erase(outbox_.begin(), outbox_.begin() + n);
    else if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK) { close_bus(); return; }
  }
  if (events & POLLIN) {
    char buffer[64]; ssize_t n = recv(bus_fd_, buffer, sizeof(buffer), 0);
    if (n == 0) { close_bus(); return; }
    if (n < 0) { if (errno != EAGAIN && errno != EWOULDBLOCK) close_bus(); return; }
    if (ready_) { close_bus(); return; }
    handshake_.append(buffer, static_cast<size_t>(n));
    if (handshake_.size() > 4 || std::string("OK01").compare(0, handshake_.size(), handshake_) != 0) { close_bus(); return; }
    if (handshake_.size() == 4) ready_ = true;
  }
}
void Hal::publish(uint32_t tick, int rssi, int channel, int bandwidth) {
  if (!ready_) return;
  std::vector<uint8_t> bytes{'H','T','0','1'}; u32(bytes, tick);
  uint16_t signal = static_cast<uint16_t>(static_cast<int16_t>(rssi));
  bytes.push_back(signal >> 8); bytes.push_back(signal & 255); bytes.push_back(channel); bytes.push_back(bandwidth);
  outbox_.insert(outbox_.end(), bytes.begin(), bytes.end());
}
