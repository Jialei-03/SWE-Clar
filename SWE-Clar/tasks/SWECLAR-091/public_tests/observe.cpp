// Public native observation adapter. Expected pane/menu values live only in the evaluator.
#include <wx/wx.h>
#include <wx/aui/aui.h>
#include <wx/toolbar.h>
#include <wx/dcscreen.h>
#include <wx/dcmemory.h>
#include <iostream>
#include <vector>
#include <stdexcept>
#include "MainWindowM.h"
#include "MainWindowV.h"
#include "MainWindowC.h"
class ObserverApp:public wxApp {public:bool OnInit(){return true;}};
wxIMPLEMENT_APP_NO_MAIN(ObserverApp);
static void str(const wxString& value){std::string s=value.ToStdString();std::cout<<'"';for(std::size_t i=0;i<s.size();++i){char c=s[i];if(c=='"'||c=='\\')std::cout<<'\\'<<c;else if(c=='\n')std::cout<<"\\n";else if(c=='\r')std::cout<<"\\r";else if(c=='\t')std::cout<<"\\t";else std::cout<<c;}std::cout<<'"';}
static void bars(wxWindow* root,std::vector<wxWindow*>& out){for(wxWindowList::compatibility_iterator n=root->GetChildren().GetFirst();n;n=n->GetNext()){wxWindow* w=n->GetData();if(dynamic_cast<wxAuiToolBar*>(w)||dynamic_cast<wxToolBar*>(w))out.push_back(w);bars(w,out);}}
static void placement(wxAuiPaneInfo& p){
 std::cout<<",\"layer\":"<<p.dock_layer<<",\"row\":"<<p.dock_row<<",\"position\":"<<p.dock_pos<<",\"proportion\":"<<p.dock_proportion<<",\"floating\":"<<p.IsFloating()<<",\"float_x\":"<<p.floating_pos.x<<",\"float_y\":"<<p.floating_pos.y<<",\"float_w\":"<<p.floating_size.x<<",\"float_h\":"<<p.floating_size.y;
}
static void mutate(wxAuiManager* m,int variant){
 wxAuiPaneInfo& left=m->GetPane("module_browser");
 left.Dock().Direction(variant==1?wxAUI_DOCK_RIGHT:wxAUI_DOCK_LEFT).Layer(variant+1).Row(variant).Position(variant+2);
 wxAuiPaneInfo& right=m->GetPane("property_window");
 right.Float().FloatingPosition(70+variant*35,90+variant*25).FloatingSize(230+variant*40,210+variant*30);
 m->Update();wxYield();
}
static void snapshot(workspace::MainWindowV* view){
 wxAuiManager* m=wxAuiManager::GetManager(view);std::cout<<"{\"shown\":"<<view->IsShown()<<",\"status\":";str(view->GetStatusBar()?view->GetStatusBar()->GetStatusText():wxString());std::cout<<",\"panes\":[";
 if(m){wxAuiPaneInfoArray& panes=m->GetAllPanes();for(std::size_t i=0;i<panes.size();++i){if(i)std::cout<<',';wxAuiPaneInfo& p=panes[i];std::cout<<"{\"name\":";str(p.name);std::cout<<",\"caption\":";str(p.caption);std::cout<<",\"window\":"<<(p.window!=NULL)<<",\"shown\":"<<p.IsShown()<<",\"direction\":"<<p.dock_direction<<",\"dockable\":"<<p.IsDockable()<<",\"close\":"<<p.HasCloseButton()<<",\"maximize\":"<<p.HasMaximizeButton();placement(p);std::cout<<'}';}}
 std::cout<<"],\"menus\":[";wxMenuBar* menu=view->GetMenuBar();if(menu)for(std::size_t i=0;i<menu->GetMenuCount();++i){if(i)std::cout<<',';str(menu->GetMenuLabelText(i));}
 std::cout<<"],\"toolbars\":[";std::vector<wxWindow*> all;bars(view,all);for(std::size_t i=0;i<all.size();++i){if(i)std::cout<<',';std::cout<<'[';bool first=true;if(wxAuiToolBar* aui=dynamic_cast<wxAuiToolBar*>(all[i])){for(std::size_t j=0;j<aui->GetToolCount();++j){wxAuiToolBarItem* tool=aui->FindToolByIndex(j);if(!tool)continue;if(!first)std::cout<<',';first=false;std::cout<<"{\"label\":";str(tool->GetLabel());std::cout<<",\"tooltip\":";str(tool->GetShortHelp());std::cout<<'}';}}else if(wxToolBar* native=dynamic_cast<wxToolBar*>(all[i])){for(std::size_t j=0;j<native->GetToolsCount();++j){wxToolBarToolBase* tool=native->GetToolByPos(j);if(!tool)continue;if(!first)std::cout<<',';first=false;std::cout<<"{\"label\":";str(tool->GetLabel());std::cout<<",\"tooltip\":";str(tool->GetShortHelp());std::cout<<'}';}}std::cout<<']';}std::cout<<"]}";
}
static void event(workspace::MainWindowV* view,const wxString& menu,const wxString& label){int id=view->GetMenuBar()->FindMenuItem(menu,label);if(id==wxNOT_FOUND)throw std::runtime_error("menu item unavailable");wxCommandEvent event(wxEVT_MENU,id);view->GetEventHandler()->ProcessEvent(event);wxYield();}
int main(int argc,char** argv){
 if(!wxEntryStart(argc,argv)||!wxTheApp->CallOnInit())return 2;wxInitAllImageHandlers();workspace::MainWindowM model;workspace::MainWindowV* view=new workspace::MainWindowV(model);workspace::MainWindowC controller(*view);view->Show();wxYield();
 wxAuiManager* m=wxAuiManager::GetManager(view);std::string mode=argc>1?argv[1]:"snapshot";std::cout<<"{\"initial\":";snapshot(view);
 try{
  if(mode!="snapshot"){
   wxAuiPaneInfo& pane=m->GetPane(wxString::FromUTF8(argv[2]));pane.Hide();mutate(m,1);std::cout<<",\"mutated\":";snapshot(view);
   if(mode=="reset")view->reset_default_perspective();
   if(mode=="roundtrip"){wxString custom=view->save_perspective();std::cout<<",\"saved\":";str(custom);pane.Show();mutate(m,2);std::cout<<",\"altered\":";snapshot(view);bool accepted=view->load_perspective(custom);std::cout<<",\"accepted\":"<<accepted;}
   if(mode=="menu"){
    wxTextCtrl* name=dynamic_cast<wxTextCtrl*>(wxWindow::FindWindowByName(wxString::FromUTF8(argv[3]),view));if(!name)throw std::runtime_error("name control unavailable");name->SetValue(wxString::FromUTF8(argv[4]));event(view,wxString::FromUTF8(argv[5]),wxString::FromUTF8(argv[6]));event(view,wxString::FromUTF8(argv[5]),wxString::FromUTF8(argv[7]));std::cout<<",\"default_menu\":";snapshot(view);event(view,wxString::FromUTF8(argv[5]),wxString::FromUTF8(argv[4]));
   }
   wxYield();std::cout<<",\"restored\":";snapshot(view);
  }
  wxSize size=view->GetSize();wxPoint pos=view->GetScreenPosition();wxBitmap bitmap(size.x,size.y);wxScreenDC screen;wxMemoryDC memory(bitmap);memory.Blit(0,0,size.x,size.y,&screen,pos.x,pos.y);memory.SelectObject(wxNullBitmap);bitmap.SaveFile("window.png",wxBITMAP_TYPE_PNG);
 }catch(const std::exception& e){std::cout<<",\"error\":";str(wxString::FromUTF8(e.what()));}
 std::cout<<"}\n";std::cout.flush();view->Destroy();wxYield();wxEntryCleanup();return 0;
}
