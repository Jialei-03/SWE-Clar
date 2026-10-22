#pragma once

#include <map>

#include <wx/aui/aui.h>
#include <wx/wx.h>

namespace workspace {

class MainWindowM;

class MainWindowV final : public wxFrame {
public:
    explicit MainWindowV(const MainWindowM& model);
    ~MainWindowV() override;

    // Restore the exact native wxAUI perspective captured at startup.
    void reset_default_perspective();

    // Save and load named perspectives for the lifetime of this window.  The
    // name is read from the inline perspective_name control.
    wxString save_perspective();
    bool load_perspective(const wxString& name);

    wxAuiManager& GetAuiManager();
    const wxString& default_perspective() const;
    wxTextCtrl* perspective_name_control() const;

    // These helpers let the controller bind menu commands that are created
    // when a new custom perspective is saved.
    bool is_custom_perspective_id(int id) const;
    wxString custom_perspective_name(int id) const;

    void set_status_text(const wxString& text);

private:
    void create_menu_bar();
    void create_workspace();
    void add_custom_perspective_menu_item(const wxString& name);

    wxAuiManager aui_manager_;
    wxString default_perspective_;
    wxMenu* windows_menu_;
    wxTextCtrl* perspective_name_;
    std::map<wxString, wxString> custom_perspectives_;
    std::map<int, wxString> custom_menu_names_;
};

}  // namespace workspace
