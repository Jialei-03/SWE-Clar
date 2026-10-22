#include "hal.hpp"
#include <array>
#include <arpa/inet.h>
#include <cerrno>
#include <fcntl.h>
#include <poll.h>
#include <stdexcept>
#include <sys/socket.h>
#include <unistd.h>

namespace {
sockaddr_in address(int port) {
  sockaddr_in result{};
  result.sin_family = AF_INET;
  result.sin_port = htons(static_cast<uint16_t>(port));
  result.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  return result;
}

void nonblocking(int fd) {
  const int flags = fcntl(fd, F_GETFL, 0);
  if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) {
    throw std::runtime_error("fcntl");
  }
}

void store_u32(uint8_t* destination, uint32_t value) {
  destination[0] = static_cast<uint8_t>(value >> 24);
  destination[1] = static_cast<uint8_t>(value >> 16);
  destination[2] = static_cast<uint8_t>(value >> 8);
  destination[3] = static_cast<uint8_t>(value);
}
}  // namespace

Hal::Hal(int board_port, int bus_port) : board_port_(board_port), bus_port_(bus_port) {
  board_fd_ = socket(AF_INET, SOCK_DGRAM, 0);
  registration_fd_ = socket(AF_INET, SOCK_STREAM, 0);
  if (board_fd_ < 0 || registration_fd_ < 0) throw std::runtime_error("socket");

  const sockaddr_in local = address(0);
  if (bind(registration_fd_, reinterpret_cast<const sockaddr*>(&local), sizeof(local)) < 0
      || listen(registration_fd_, 8) < 0) {
    throw std::runtime_error("registration listener");
  }

  sockaddr_in bound = local;
  socklen_t length = sizeof(bound);
  if (getsockname(registration_fd_, reinterpret_cast<sockaddr*>(&bound), &length) < 0) {
    throw std::runtime_error("getsockname");
  }
  registration_port_ = ntohs(bound.sin_port);
  nonblocking(registration_fd_);
}

Hal::~Hal() {
  stop_registration();
  close_bus();
  if (board_fd_ >= 0) close(board_fd_);
}

void Hal::stop_registration() {
  if (registration_fd_ >= 0) close(registration_fd_);
  registration_fd_ = -1;
}

void Hal::service_registration() {
  while (registration_fd_ >= 0) {
    const int client = accept(registration_fd_, nullptr, nullptr);
    if (client < 0) return;
    // SETUP is only six bytes, so a normal TCP send on a freshly accepted
    // socket completes without waiting for a peer acknowledgement.
    (void)send(client, "SETUP\n", 6, MSG_NOSIGNAL);
    close(client);
  }
}

void Hal::board_send(const uint8_t* bytes, std::size_t length) {
  const sockaddr_in destination = address(board_port_);
  const ssize_t sent = sendto(board_fd_, bytes, length, 0,
                              reinterpret_cast<const sockaddr*>(&destination), sizeof(destination));
  if (sent != static_cast<ssize_t>(length)) throw std::runtime_error("virtual board output");
}

void Hal::gpio(uint32_t tick, bool level) {
  std::array<uint8_t, 6> bytes{};
  bytes[0] = 1;
  store_u32(bytes.data() + 1, tick);
  bytes[5] = level ? 1 : 0;
  board_send(bytes.data(), bytes.size());
}

void Hal::advertise(uint32_t tick) {
  std::array<uint8_t, 5> bytes{};
  bytes[0] = 2;
  store_u32(bytes.data() + 1, tick);
  board_send(bytes.data(), bytes.size());
}

void Hal::queue_hello() {
  outbox_ = {'H', 'B', '0', '1'};
  hello_sent_ = false;
}

void Hal::open_bus() {
  if (bus_fd_ >= 0) return;

  const int fd = socket(AF_INET, SOCK_STREAM, 0);
  if (fd < 0) return;
  try {
    nonblocking(fd);
  } catch (...) {
    close(fd);
    return;
  }

  bus_fd_ = fd;
  connecting_ = true;
  ready_ = false;
  hello_sent_ = false;
  handshake_.clear();
  outbox_.clear();

  const sockaddr_in destination = address(bus_port_);
  const int result = connect(bus_fd_, reinterpret_cast<const sockaddr*>(&destination), sizeof(destination));
  if (result == 0) {
    connecting_ = false;
    queue_hello();
  } else if (errno != EINPROGRESS && errno != EALREADY) {
    close_bus();
  }
}

void Hal::close_bus() {
  if (bus_fd_ >= 0) close(bus_fd_);
  bus_fd_ = -1;
  connecting_ = false;
  ready_ = false;
  hello_sent_ = false;
  handshake_.clear();
  // This is intentionally cleared with the descriptor: health records must
  // never cross a connection boundary.
  outbox_.clear();
}

short Hal::bus_events() const {
  if (bus_fd_ < 0) return 0;
  short events = POLLIN;
  if (connecting_ || !outbox_.empty()) events = static_cast<short>(events | POLLOUT);
  return events;
}

bool Hal::flush_bus_output() {
  while (!outbox_.empty()) {
    const ssize_t sent = send(bus_fd_, outbox_.data(), outbox_.size(), MSG_NOSIGNAL);
    if (sent > 0) {
      outbox_.erase(outbox_.begin(), outbox_.begin() + sent);
      continue;
    }
    if (sent < 0 && (errno == EINTR)) continue;
    if (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) return true;
    return false;
  }
  return true;
}

void Hal::service_bus(short events) {
  if (bus_fd_ < 0) return;
  if (events & POLLNVAL) {
    close_bus();
    return;
  }

  if (connecting_) {
    if (events & POLLOUT) {
      int error = 0;
      socklen_t size = sizeof(error);
      if (getsockopt(bus_fd_, SOL_SOCKET, SO_ERROR, &error, &size) < 0 || error != 0) {
        close_bus();
        return;
      }
      connecting_ = false;
      queue_hello();
    } else if (events & (POLLERR | POLLHUP)) {
      close_bus();
      return;
    } else {
      // A connecting descriptor has no valid handshake to read yet.
      return;
    }
  }

  if (events & POLLERR) {
    close_bus();
    return;
  }

  // The only bytes queued before readiness are the greeting.  Always drain
  // that greeting before considering input, including the immediate-connect
  // case where POLLIN and POLLOUT can be reported together.  This keeps the
  // protocol order HB01 -> OK01 independent of poll timing.
  if (!ready_ && !hello_sent_) {
    if (!flush_bus_output()) {
      close_bus();
      return;
    }
    if (!outbox_.empty()) return;
    hello_sent_ = true;
  }

  if (events & POLLIN) {
    char buffer[64];
    ssize_t received;
    do {
      received = recv(bus_fd_, buffer, sizeof(buffer), 0);
    } while (received < 0 && errno == EINTR);

    if (received == 0) {
      close_bus();
      return;
    }
    if (received < 0) {
      if (errno != EAGAIN && errno != EWOULDBLOCK) close_bus();
      return;
    }

    if (ready_) {
      // The documented peer sends no bytes after OK01.  Treat any such
      // traffic as a failed connection rather than mixing it with frames.
      close_bus();
      return;
    }

    handshake_.append(buffer, static_cast<size_t>(received));
    const std::string expected = "OK01";
    if (handshake_.size() > expected.size()
        || expected.compare(0, handshake_.size(), handshake_) != 0) {
      close_bus();
      return;
    }
    if (handshake_.size() == expected.size()) ready_ = true;
  }

  // POLLHUP may be reported together with the final readable bytes.  Once
  // those bytes have been consumed the peer is still gone, so discard the
  // connection (and any unsent old-connection records).
  if (events & POLLHUP) {
    close_bus();
    return;
  }

  if ((events & POLLOUT) && !outbox_.empty() && !flush_bus_output()) {
    close_bus();
  }
}

void Hal::publish(uint32_t tick, int rssi, int channel, int bandwidth) {
  if (!ready_) return;

  std::array<uint8_t, 12> frame{};
  frame[0] = 'H';
  frame[1] = 'T';
  frame[2] = '0';
  frame[3] = '1';
  store_u32(frame.data() + 4, tick);
  const uint16_t signal = static_cast<uint16_t>(static_cast<int16_t>(rssi));
  frame[8] = static_cast<uint8_t>(signal >> 8);
  frame[9] = static_cast<uint8_t>(signal);
  frame[10] = static_cast<uint8_t>(channel);
  frame[11] = static_cast<uint8_t>(bandwidth);
  outbox_.insert(outbox_.end(), frame.begin(), frame.end());
}
