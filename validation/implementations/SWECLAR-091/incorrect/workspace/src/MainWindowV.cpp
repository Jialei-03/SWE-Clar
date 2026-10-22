#include "MainWindowV.h"

#include "MainWindowG.h"
#include "MainWindowM.h"

namespace workspace {
namespace {

wxAuiPaneInfo workspace_pane(const char* name,
                             const char* caption,
                             wxAuiPaneInfo position) {
    return position.Name(wxString(name))
        .Caption(wxString(caption))
        .Dockable(true)
        .Floatable(true)
        .Movable(true)
        .Resizable(true)
        .CloseButton(true)
        .MaximizeButton(true)
        .CaptionVisible(true);
}

}  // namespace

MainWindowV::MainWindowV(const MainWindowM& model)
    : wxFrame(nullptr,
              wxID_ANY,
              wxString(constants::kApplicationTitle),
              wxDefaultPosition,
              wxSize(1100, 720),
              wxDEFAULT_FRAME_STYLE | wxCLIP_CHILDREN),
      aui_manager_(this),
      default_perspective_(),
      windows_menu_(nullptr),
      perspective_name_(nullptr),
      custom_perspectives_(),
      custom_menu_names_() {
    // The model is deliberately portable.  Construction of the visual shell
    // does not require a wxWidgets type in the model.
    (void)model;

    SetName("main_window");
    SetMinSize(wxSize(760, 480));

    create_menu_bar();

    wxStatusBar* status_bar = CreateStatusBar(1);
    status_bar->SetName("status_bar");
    SetStatusText(wxString(constants::kStatusReady));

    create_workspace();

    // Save the actual manager serialization only after every pane has been
    // added and laid out.  This is the source of truth for reset and is also
    // useful to native observers of the window.
    aui_manager_.Update();
    default_perspective_ = aui_manager_.SavePerspective();
}

MainWindowV::~MainWindowV() {
    // Explicitly detach the manager before wxFrame tears down its children.
    aui_manager_.UnInit();
}

void MainWindowV::create_menu_bar() {
    wxMenuBar* menu_bar = new wxMenuBar();

    wxMenu* file_menu = new wxMenu();
    file_menu->Append(wxID_EXIT,
                      wxString(constants::kExitLabel),
                      wxString("Close the workspace"));

    wxMenu* edit_menu = new wxMenu();
    edit_menu->Append(constants::kMenuUndo,
                      wxString(constants::kUndoLabel),
                      wxString("Undo the last edit"));
    edit_menu->Append(constants::kMenuResetLayout,
                      wxString(constants::kResetLayoutLabel),
                      wxString("Restore the default workspace layout"));

    wxMenu* verify_menu = new wxMenu();
    verify_menu->Append(constants::kMenuVerifyNow,
                        wxString(constants::kVerifyNowLabel),
                        wxString("Verify the current workspace"));

    wxMenu* tools_menu = new wxMenu();
    tools_menu->Append(constants::kMenuRefresh,
                       wxString(constants::kRefreshLabel),
                       wxString("Refresh the workspace"));
    tools_menu->Append(constants::kMenuPreferences,
                       wxString(constants::kPreferencesLabel),
                       wxString("Workspace preferences"));

    windows_menu_ = new wxMenu();
    windows_menu_->Append(constants::kMenuSavePerspective,
                          wxString(constants::kSavePerspectiveLabel),
                          wxString("Save the current named perspective"));
    windows_menu_->AppendSeparator();
    windows_menu_->Append(constants::kMenuDefaultPerspective,
                          wxString(constants::kDefaultPerspectiveLabel),
                          wxString("Restore the startup perspective"));

    wxMenu* help_menu = new wxMenu();
    help_menu->Append(constants::kMenuAbout,
                      wxString(constants::kAboutLabel),
                      wxString("About the engineering workspace"));

    menu_bar->Append(file_menu, wxString(constants::kFileMenu));
    menu_bar->Append(edit_menu, wxString(constants::kEditMenu));
    menu_bar->Append(verify_menu, wxString(constants::kVerifyMenu));
    menu_bar->Append(tools_menu, wxString(constants::kToolsMenu));
    menu_bar->Append(windows_menu_, wxString(constants::kWindowsMenu));
    menu_bar->Append(help_menu, wxString(constants::kHelpMenu));
    SetMenuBar(menu_bar);
}

void MainWindowV::create_workspace() {
    // Two real wxToolBar instances are used instead of drawing toolbar-like
    // controls in a panel.  Native probes can therefore inspect their tools
    // and short-help text directly.
    wxToolBar* toolbar = new wxToolBar(this,
                                       wxID_ANY,
                                       wxDefaultPosition,
                                       wxDefaultSize,
                                       wxTB_HORIZONTAL | wxTB_TEXT | wxTB_NOICONS);
    toolbar->SetName(wxString(constants::kToolbarName));
    toolbar->AddTool(constants::kToolUpdate,
                     wxString(constants::kUpdateLabel),
                     wxNullBitmap,
                     wxString(constants::kUpdateTooltip));
    toolbar->AddTool(constants::kToolSelect,
                     wxString(constants::kSelectLabel),
                     wxNullBitmap,
                     wxString(constants::kSelectTooltip));
    toolbar->AddTool(constants::kToolUnselect,
                     wxString(constants::kUnselectLabel),
                     wxNullBitmap,
                     wxString(constants::kUnselectTooltip));
    toolbar->AddTool(constants::kToolCancel,
                     wxString(constants::kCancelLabel),
                     wxNullBitmap,
                     wxString(constants::kCancelTooltip));
    toolbar->Realize();

    wxToolBar* verification_toolbar = new wxToolBar(this,
                                                    wxID_ANY,
                                                    wxDefaultPosition,
                                                    wxDefaultSize,
                                                    wxTB_HORIZONTAL | wxTB_TEXT | wxTB_NOICONS);
    verification_toolbar->SetName("verification_toolbar");
    verification_toolbar->AddTool(constants::kToolLint,
                                  wxString(constants::kLintLabel),
                                  wxNullBitmap,
                                  wxString(constants::kLintTooltip));
    verification_toolbar->AddTool(constants::kToolAnalyze,
                                  wxString(constants::kAnalyzeLabel),
                                  wxNullBitmap,
                                  wxString(constants::kAnalyzeTooltip));
    verification_toolbar->AddTool(constants::kToolVerify,
                                  wxString(constants::kVerifyLabel),
                                  wxNullBitmap,
                                  wxString(constants::kVerifyTooltip));
    verification_toolbar->AddTool(constants::kToolAutoVerify,
                                  wxString(constants::kAutoVerifyLabel),
                                  wxNullBitmap,
                                  wxString(constants::kAutoVerifyTooltip));
    verification_toolbar->Realize();

    wxPanel* module_browser = new wxPanel(this, wxID_ANY);
    module_browser->SetName(wxString(constants::kModuleBrowserName));
    wxBoxSizer* module_sizer = new wxBoxSizer(wxVERTICAL);
    module_sizer->Add(new wxStaticText(module_browser,
                                       wxID_ANY,
                                       wxString("Workspace modules")),
                      0,
                      wxALL | wxEXPAND,
                      6);
    wxListBox* module_list = new wxListBox(module_browser, wxID_ANY);
    module_list->Append("Core");
    module_list->Append("Editor");
    module_list->Append("Verification");
    module_sizer->Add(module_list, 1, wxLEFT | wxRIGHT | wxBOTTOM | wxEXPAND, 6);
    module_browser->SetSizer(module_sizer);

    wxTextCtrl* code_window = new wxTextCtrl(this,
                                             wxID_ANY,
                                             wxString("// Select a module to begin editing\n"),
                                             wxDefaultPosition,
                                             wxDefaultSize,
                                             wxTE_MULTILINE | wxTE_RICH2);
    code_window->SetName(wxString(constants::kCodeWindowName));

    wxPanel* property_window = new wxPanel(this, wxID_ANY);
    property_window->SetName(wxString(constants::kPropertyWindowName));
    wxFlexGridSizer* property_sizer = new wxFlexGridSizer(2, 6, 6);
    property_sizer->Add(new wxStaticText(property_window, wxID_ANY, "Name"),
                        0,
                        wxALIGN_CENTER_VERTICAL);
    property_sizer->Add(new wxStaticText(property_window, wxID_ANY, "Workspace"),
                        0,
                        wxEXPAND);
    property_sizer->Add(new wxStaticText(property_window, wxID_ANY, "State"),
                        0,
                        wxALIGN_CENTER_VERTICAL);
    property_sizer->Add(new wxStaticText(property_window, wxID_ANY, "Ready"),
                        0,
                        wxEXPAND);
    property_sizer->AddGrowableCol(1, 1);
    wxBoxSizer* property_outer = new wxBoxSizer(wxVERTICAL);
    property_outer->Add(property_sizer, 0, wxALL | wxEXPAND, 8);
    property_window->SetSizer(property_outer);

    wxTextCtrl* message_box = new wxTextCtrl(this,
                                             wxID_ANY,
                                             wxString("Workspace ready.\n"),
                                             wxDefaultPosition,
                                             wxDefaultSize,
                                             wxTE_MULTILINE | wxTE_READONLY | wxTE_RICH2);
    message_box->SetName(wxString(constants::kMessageBoxName));

    wxPanel* command_line = new wxPanel(this, wxID_ANY);
    command_line->SetName(wxString(constants::kCommandLineName));
    wxBoxSizer* command_sizer = new wxBoxSizer(wxVERTICAL);
    wxBoxSizer* perspective_sizer = new wxBoxSizer(wxHORIZONTAL);
    perspective_sizer->Add(new wxStaticText(command_line,
                                            wxID_ANY,
                                            wxString("Perspective name")),
                           0,
                           wxALIGN_CENTER_VERTICAL | wxRIGHT,
                           6);
    perspective_name_ = new wxTextCtrl(command_line,
                                       wxID_ANY,
                                       wxString(constants::kPerspectiveNameDefault),
                                       wxDefaultPosition,
                                       wxDefaultSize,
                                       wxTE_PROCESS_ENTER);
    perspective_name_->SetName(wxString(constants::kPerspectiveNameControl));
    perspective_sizer->Add(perspective_name_, 1, wxEXPAND);
    command_sizer->Add(perspective_sizer, 0, wxALL | wxEXPAND, 6);
    wxTextCtrl* command_entry = new wxTextCtrl(command_line,
                                               wxID_ANY,
                                               wxEmptyString,
                                               wxDefaultPosition,
                                               wxDefaultSize,
                                               wxTE_PROCESS_ENTER);
    command_entry->SetName("command_entry");
    command_sizer->Add(command_entry, 0, wxLEFT | wxRIGHT | wxBOTTOM | wxEXPAND, 6);
    command_line->SetSizer(command_sizer);

    wxPanel* property_manager = new wxPanel(this, wxID_ANY);
    property_manager->SetName(wxString(constants::kPropertyManagerName));
    wxBoxSizer* manager_sizer = new wxBoxSizer(wxVERTICAL);
    manager_sizer->Add(new wxStaticText(property_manager,
                                        wxID_ANY,
                                        wxString("Managed properties")),
                       0,
                       wxALL | wxEXPAND,
                       6);
    wxListBox* manager_list = new wxListBox(property_manager, wxID_ANY);
    manager_list->Append("Layout");
    manager_list->Append("Selection");
    manager_list->Append("Verification");
    manager_sizer->Add(manager_list, 1, wxLEFT | wxRIGHT | wxBOTTOM | wxEXPAND, 6);
    property_manager->SetSizer(manager_sizer);

    // Toolbars occupy the top dock rows.  The six workspace panes span the
    // conventional left, center, right and bottom AUI dock positions.
    aui_manager_.AddPane(
        toolbar,
        wxAuiPaneInfo().ToolbarPane()
            .Name(wxString(constants::kToolbarName))
            .Caption(wxString(constants::kToolbarCaption))
            .Top()
            .Layer(10)
            .Row(0)
            .Position(0)
            .CloseButton(false)
            .MaximizeButton(false));
    aui_manager_.AddPane(
        verification_toolbar,
        wxAuiPaneInfo().ToolbarPane()
            .Name("verification_toolbar")
            .Caption(wxString(constants::kVerificationToolbarCaption))
            .Top()
            .Layer(10)
            .Row(1)
            .Position(0)
            .CloseButton(false)
            .MaximizeButton(false));
    aui_manager_.AddPane(
        module_browser,
        workspace_pane(constants::kModuleBrowserName,
                       constants::kModuleBrowserCaption,
                       wxAuiPaneInfo().Left().Layer(0).Row(0).Position(0))
            .BestSize(220, 420));
    aui_manager_.AddPane(
        code_window,
        workspace_pane(constants::kCodeWindowName,
                       constants::kCodeWindowCaption,
                       wxAuiPaneInfo().CenterPane())
            .BestSize(620, 420));
    aui_manager_.AddPane(
        property_window,
        workspace_pane(constants::kPropertyWindowName,
                       constants::kPropertyWindowCaption,
                       wxAuiPaneInfo().Right().Layer(0).Row(0).Position(0))
            .BestSize(240, 230));
    aui_manager_.AddPane(
        property_manager,
        workspace_pane(constants::kPropertyManagerName,
                       constants::kPropertyManagerCaption,
                       wxAuiPaneInfo().Right().Layer(0).Row(1).Position(0))
            .BestSize(240, 230));
    aui_manager_.AddPane(
        message_box,
        workspace_pane(constants::kMessageBoxName,
                       constants::kMessageBoxCaption,
                       wxAuiPaneInfo().Bottom().Layer(0).Row(0).Position(0))
            .BestSize(620, 130));
    aui_manager_.AddPane(
        command_line,
        workspace_pane(constants::kCommandLineName,
                       constants::kCommandLineCaption,
                       wxAuiPaneInfo().Bottom().Layer(0).Row(1).Position(0))
            .BestSize(620, 90));
}

void MainWindowV::reset_default_perspective() {
    if (!default_perspective_.IsEmpty()) {
        aui_manager_.SavePerspective();
    }
}

wxString MainWindowV::save_perspective() {
    aui_manager_.Update();

    wxString name = perspective_name_ == nullptr
                        ? wxString(constants::kPerspectiveNameDefault)
                        : perspective_name_->GetValue();
    name.Trim(true);
    name.Trim(false);
    if (name.IsEmpty()) {
        name = wxString(constants::kPerspectiveNameDefault);
    }

    custom_perspectives_[name] = aui_manager_.SavePerspective();
    add_custom_perspective_menu_item(name);
    return name;
}

bool MainWindowV::load_perspective(const wxString& name) {
    if (name == wxString(constants::kDefaultPerspectiveLabel)) {
        reset_default_perspective();
        return true;
    }

    std::map<wxString, wxString>::const_iterator found = custom_perspectives_.find(name);
    if (found == custom_perspectives_.end() || found->second.IsEmpty()) {
        return false;
    }

    const bool loaded = aui_manager_.LoadPerspective(found->second, true);
    if (loaded && perspective_name_ != nullptr) {
        perspective_name_->ChangeValue(name);
    }
    return loaded;
}

wxAuiManager& MainWindowV::GetAuiManager() {
    return aui_manager_;
}

const wxString& MainWindowV::default_perspective() const {
    return default_perspective_;
}

wxTextCtrl* MainWindowV::perspective_name_control() const {
    return perspective_name_;
}

bool MainWindowV::is_custom_perspective_id(int id) const {
    return custom_menu_names_.find(id) != custom_menu_names_.end();
}

wxString MainWindowV::custom_perspective_name(int id) const {
    std::map<int, wxString>::const_iterator found = custom_menu_names_.find(id);
    if (found == custom_menu_names_.end()) {
        return wxEmptyString;
    }
    return found->second;
}

void MainWindowV::set_status_text(const wxString& text) {
    SetStatusText(text);
}

void MainWindowV::add_custom_perspective_menu_item(const wxString& name) {
    if (windows_menu_ == nullptr) {
        return;
    }

    for (std::map<int, wxString>::const_iterator item = custom_menu_names_.begin();
         item != custom_menu_names_.end();
         ++item) {
        if (item->second == name) {
            return;
        }
    }

    const int id = wxWindow::NewControlId();
    windows_menu_->Append(id, name, wxString("Load this saved perspective"));
    custom_menu_names_[id] = name;
    windows_menu_->UpdateUI();
}

}  // namespace workspace
