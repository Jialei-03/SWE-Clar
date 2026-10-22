#include "MainWindowC.h"

#include "MainWindowG.h"

namespace workspace {

MainWindowC::MainWindowC(MainWindowV& view)
    : view_(&view) {
    // Dynamic bindings keep the view declarative and make the controller the
    // single owner of interaction policy.
    view.Bind(wxEVT_MENU, &MainWindowC::on_menu, this);
    // On GTK, wxEVT_TOOL is an alias for wxEVT_MENU.  Restrict the tool
    // binding to the application-owned tool ID range so it cannot consume
    // menu commands before on_menu sees them.
    view.Bind(wxEVT_TOOL,
              &MainWindowC::on_tool,
              this,
              constants::kToolUpdate,
              constants::kToolAutoVerify);
}

void MainWindowC::on_menu(wxCommandEvent& event) {
    if (view_ == nullptr) {
        return;
    }

    const int id = event.GetId();
    if (id == wxID_EXIT) {
        view_->Close(true);
        return;
    }

    if (id == constants::kMenuSavePerspective) {
        const wxString name = view_->save_perspective();
        view_->set_status_text(wxString("Saved perspective: ") + name);
        return;
    }

    if (id == constants::kMenuDefaultPerspective) {
        view_->reset_default_perspective();
        view_->set_status_text(wxString(constants::kStatusReady));
        return;
    }

    if (view_->is_custom_perspective_id(id)) {
        const wxString name = view_->custom_perspective_name(id);
        if (view_->load_perspective(name)) {
            view_->set_status_text(wxString("Loaded perspective: ") + name);
        }
        return;
    }

    if (id == constants::kMenuResetLayout) {
        view_->reset_default_perspective();
        view_->set_status_text(wxString(constants::kStatusReady));
    } else if (id == constants::kMenuUndo) {
        view_->set_status_text(wxString("Undo is not active in the shell"));
    } else if (id == constants::kMenuRefresh) {
        view_->set_status_text(wxString("Workspace refreshed"));
    } else if (id == constants::kMenuVerifyNow) {
        view_->set_status_text(wxString("Verification is ready"));
    } else if (id == constants::kMenuPreferences) {
        view_->set_status_text(wxString("Preferences are not required for the shell"));
    } else if (id == constants::kMenuAbout) {
        view_->set_status_text(wxString(constants::kApplicationTitle));
    }
}

void MainWindowC::on_tool(wxCommandEvent& event) {
    if (view_ == nullptr) {
        return;
    }

    switch (event.GetId()) {
    case constants::kToolUpdate:
        view_->set_status_text(wxString("Workspace updated"));
        break;
    case constants::kToolSelect:
        view_->set_status_text(wxString("Selection active"));
        break;
    case constants::kToolUnselect:
        view_->set_status_text(wxString("Selection cleared"));
        break;
    case constants::kToolCancel:
        view_->set_status_text(wxString("Operation cancelled"));
        break;
    case constants::kToolLint:
        view_->set_status_text(wxString("Lint is ready"));
        break;
    case constants::kToolAnalyze:
        view_->set_status_text(wxString("Analysis is ready"));
        break;
    case constants::kToolVerify:
        view_->set_status_text(wxString("Verification is ready"));
        break;
    case constants::kToolAutoVerify:
        view_->set_status_text(event.IsChecked()
                                   ? wxString("Auto-Verify enabled")
                                   : wxString("Auto-Verify disabled"));
        break;
    default:
        break;
    }
}

}  // namespace workspace
