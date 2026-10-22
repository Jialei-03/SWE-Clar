cmake_minimum_required(VERSION 3.16)
project(fcb_wx_workspace LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

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
