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
        if (argc >= 2 && wxString(argv[1]) == wxString("--dump-layout")) {
            std::cout << model.layout_json() << '\n';
            cli_mode_ = true;
            return true;
        }

        view_ = new MainWindowV(model);
        controller_.reset(new MainWindowC(*view_));
        SetTopWindow(view_);
        view_->Show(true);

        if (argc >= 2 && wxString(argv[1]) == wxString("--smoke")) {
            smoke_mode_ = true;
            CallAfter(&WorkspaceApp::finish_smoke);
        }
        return true;
    }

    int OnRun() override {
        return cli_mode_ ? 0 : wxApp::OnRun();
    }

private:
    void finish_smoke() {
        // Close the real frame through wx's normal close path, then leave the
        // event loop.  wxWidgets owns top-level windows after they are shown;
        // the raw pointer is intentionally not deleted here.
        if (smoke_mode_ && view_ != nullptr) {
            view_->Close(true);
            view_ = nullptr;
        }
        ExitMainLoop();
    }

    MainWindowV* view_{nullptr};
    std::unique_ptr<MainWindowC> controller_;
    bool cli_mode_{false};
    bool smoke_mode_{false};
};

}  // namespace workspace

wxIMPLEMENT_APP(workspace::WorkspaceApp);
