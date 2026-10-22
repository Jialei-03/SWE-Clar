#include <wx/wx.h>
#include <wx/aui/aui.h>
#include <unistd.h>
#include <iostream>
class HealthApp:public wxApp {public:bool OnInit(){return true;}};
wxIMPLEMENT_APP_NO_MAIN(HealthApp);
int main(int argc,char** argv){if(getuid()!=1000)return 1;if(!wxEntryStart(argc,argv)||!wxTheApp->CallOnInit())return 2;wxFrame* frame=new wxFrame(NULL,wxID_ANY,"Synthetic GUI health",wxDefaultPosition,wxSize(400,260));wxAuiManager manager(frame);manager.AddPane(new wxTextCtrl(frame,wxID_ANY,"Prepared wxWidgets"),wxAuiPaneInfo().Name("health").CenterPane());manager.Update();frame->Show();wxYield();bool ok=frame->IsShown()&&manager.GetPane("health").IsOk();manager.UnInit();frame->Destroy();wxYield();wxEntryCleanup();std::cout<<(ok?"native-gui-ready":"failed")<<std::endl;return ok?0:3;}
