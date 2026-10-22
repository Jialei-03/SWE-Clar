cmake_minimum_required(VERSION 3.16)
project(fcb_wx_workspace LANGUAGES CXX)

# The reference shell intentionally targets the portable C++11 toolchain.
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(wxWidgets REQUIRED COMPONENTS core base aui)
include(${wxWidgets_USE_FILE})

add_executable(workspace_gui
    src/App.cpp
    src/MainWindowM.cpp
    src/MainWindowV.cpp
    src/MainWindowC.cpp
)
target_include_directories(workspace_gui PRIVATE src)
target_link_libraries(workspace_gui PRIVATE ${wxWidgets_LIBRARIES})

if (CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(workspace_gui PRIVATE -pedantic-errors)
endif()
