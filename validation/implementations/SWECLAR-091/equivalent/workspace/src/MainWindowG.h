#pragma once

// UI strings and command identifiers live in this header so that the view does
// not have to duplicate user-facing text.  It deliberately has no wxWidgets
// dependency; the model can include the same project constants if needed.
namespace workspace {
namespace constants {

constexpr char kApplicationTitle[] = "Engineering Workspace";
constexpr char kStatusReady[] = "Ready";

constexpr char kModuleBrowserName[] = "module_browser";
constexpr char kToolbarName[] = "toolbar";
constexpr char kCodeWindowName[] = "code_window";
constexpr char kPropertyWindowName[] = "property_window";
constexpr char kMessageBoxName[] = "message_box";
constexpr char kCommandLineName[] = "command_line";
constexpr char kPropertyManagerName[] = "property_manager";
constexpr char kPerspectiveNameControl[] = "perspective_name";

constexpr char kModuleBrowserCaption[] = "Module Browser";
constexpr char kToolbarCaption[] = "Toolbar";
constexpr char kVerificationToolbarCaption[] = "Verification";
constexpr char kCodeWindowCaption[] = "Code Window";
constexpr char kPropertyWindowCaption[] = "Property Window";
constexpr char kMessageBoxCaption[] = "Message Box";
constexpr char kCommandLineCaption[] = "Command Line Interface";
constexpr char kPropertyManagerCaption[] = "Property Manager";

constexpr char kFileMenu[] = "File";
constexpr char kEditMenu[] = "Edit";
constexpr char kVerifyMenu[] = "Verify";
constexpr char kToolsMenu[] = "Tools";
constexpr char kWindowsMenu[] = "Windows";
constexpr char kHelpMenu[] = "Help";

constexpr char kSavePerspectiveLabel[] = "Save perspective";
constexpr char kDefaultPerspectiveLabel[] = "Default perspective";
constexpr char kResetLayoutLabel[] = "Reset layout";
constexpr char kExitLabel[] = "Exit";
constexpr char kUndoLabel[] = "Undo";
constexpr char kRefreshLabel[] = "Refresh";
constexpr char kVerifyNowLabel[] = "Verify now";
constexpr char kPreferencesLabel[] = "Preferences";
constexpr char kAboutLabel[] = "About";

constexpr char kPerspectiveNameDefault[] = "Custom perspective";

constexpr char kUpdateLabel[] = "Update";
constexpr char kSelectLabel[] = "Select";
constexpr char kUnselectLabel[] = "Unselect";
constexpr char kCancelLabel[] = "Cancel";
constexpr char kLintLabel[] = "Lint";
constexpr char kAnalyzeLabel[] = "Analyze";
constexpr char kVerifyLabel[] = "Verify";
constexpr char kAutoVerifyLabel[] = "Auto-Verify";

constexpr char kUpdateTooltip[] = "Update the workspace";
constexpr char kSelectTooltip[] = "Select the current item";
constexpr char kUnselectTooltip[] = "Clear the current selection";
constexpr char kCancelTooltip[] = "Cancel the current operation";
constexpr char kLintTooltip[] = "Run the code linter";
constexpr char kAnalyzeTooltip[] = "Analyze the current code";
constexpr char kVerifyTooltip[] = "Verify the current code";
constexpr char kAutoVerifyTooltip[] = "Toggle automatic verification";

// Application-owned IDs are kept in a range separate from wx's stock IDs.
enum CommandId {
    kMenuSavePerspective = 4100,
    kMenuDefaultPerspective,
    kMenuResetLayout,
    kMenuUndo,
    kMenuRefresh,
    kMenuVerifyNow,
    kMenuPreferences,
    kMenuAbout,
    kToolUpdate,
    kToolSelect,
    kToolUnselect,
    kToolCancel,
    kToolLint,
    kToolAnalyze,
    kToolVerify,
    kToolAutoVerify
};

}  // namespace constants
}  // namespace workspace
