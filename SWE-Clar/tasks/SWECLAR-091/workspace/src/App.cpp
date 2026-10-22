#include <iostream>
#include <memory>

#include <wx/wx.h>

#include "MainWindowC.h"
#include "MainWindowM.h"
#include "MainWindowV.h"

namespace workspace {

class WorkspaceApp final : public wxApp {
public:
    bool OnInit() override {
        MainWindowM model;
        if (argc >= 2 && wxString(argv[1]) == "--dump-layout") {
            std::cout << model.layout_json() << '\n';
            cli_mode_ = true;
            return true;
        }
        view_ = std::make_unique<MainWindowV>();
        controller_ = std::make_unique<MainWindowC>(*view_);
        view_->Show();
        return true;
    }

    int OnRun() override {
        return cli_mode_ ? 0 : wxApp::OnRun();
    }

private:
    std::unique_ptr<MainWindowV> view_;
    std::unique_ptr<MainWindowC> controller_;
    bool cli_mode_{false};
};

}  // namespace workspace

wxIMPLEMENT_APP(workspace::WorkspaceApp);
