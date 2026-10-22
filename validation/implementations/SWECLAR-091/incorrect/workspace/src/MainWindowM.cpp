#include "MainWindowM.h"

namespace workspace {

std::string MainWindowM::layout_json() const {
    return "{\"panes\":[\"module_browser\",\"toolbar\",\"code_window\",\"property_window\",\"message_box\",\"command_line\",\"property_manager\"],\"status_text\":\"Ready\"}";
}

}  // namespace workspace
