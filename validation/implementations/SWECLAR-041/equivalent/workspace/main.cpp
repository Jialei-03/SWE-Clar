#include "controller.hpp"
#include <cerrno>
#include <cstdlib>
#include <iostream>
#include <poll.h>
#include <signal.h>
#include <stdexcept>
#include <unistd.h>

int main(int argc, char** argv) {
  try {
    int board_port = 0, bus_port = 0;
    for (int i = 1; i + 1 < argc; i += 2) {
      std::string key = argv[i]; int value = std::stoi(argv[i+1]);
      if (value < 1 || value > 65535) throw std::runtime_error("port");
      if (key == "--board-port") board_port = value;
      else if (key == "--bus-port") bus_port = value;
      else throw std::runtime_error("argument");
    }
    if (argc != 5 || !board_port || !bus_port) throw std::runtime_error("Provide --board-port and --bus-port");
    signal(SIGPIPE, SIG_IGN); std::cout << std::unitbuf;
    Hal hal(board_port, bus_port); Controller controller(hal);
    std::cout << "{\"registration_port\":" << hal.registration_port() << "}\n";
    std::string pending; bool dropping = false;
    while (!controller.quitting()) {
      pollfd fds[] = {{STDIN_FILENO, POLLIN, 0}, {hal.registration_fd(), POLLIN, 0}, {hal.bus_fd(), hal.bus_events(), 0}};
      int result = poll(fds, 3, -1);
      if (result < 0) { if (errno == EINTR) continue; throw std::runtime_error("poll"); }
      hal.service_bus(fds[2].revents); controller.link_changed();
      if (fds[1].revents & POLLIN) hal.service_registration();
      if (fds[0].revents & (POLLIN | POLLHUP)) {
        char bytes[512]; ssize_t n = read(STDIN_FILENO, bytes, sizeof(bytes));
        if (n <= 0) break;
        for (ssize_t i = 0; i < n; ++i) {
          if (bytes[i] == '\n') {
            std::cout << (dropping ? "{\"ok\":false,\"error\":\"invalid_command\"}" : controller.command(pending)) << "\n";
            pending.clear(); dropping = false;
            if (controller.quitting()) break;
          } else if (!dropping) {
            if (pending.size() >= 256) { pending.clear(); dropping = true; }
            else pending.push_back(bytes[i]);
          }
        }
      }
    }
    return 0;
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 2; }
}
