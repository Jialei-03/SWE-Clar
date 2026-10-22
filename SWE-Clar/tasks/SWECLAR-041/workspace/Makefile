CXX = g++
CXXFLAGS = -std=c++17 -O2 -Wall -Wextra -Werror

build/firmware: main.cpp controller.cpp hal.cpp controller.hpp hal.hpp
	mkdir -p build
	$(CXX) $(CXXFLAGS) main.cpp controller.cpp hal.cpp -o $@

.PHONY: clean
clean:
	rm -rf build
