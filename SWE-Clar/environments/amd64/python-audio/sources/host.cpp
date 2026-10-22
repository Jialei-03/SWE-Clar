// Offline VST3 execution probe. Input rows: start_frame end_frame midi_pitch velocity.
#include "public.sdk/source/vst/hosting/module.h"
#include "public.sdk/source/vst/hosting/plugprovider.h"
#include "public.sdk/source/vst/hosting/hostclasses.h"
#include "public.sdk/source/vst/hosting/eventlist.h"
#include "pluginterfaces/vst/ivstaudioprocessor.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
using namespace Steinberg;
using namespace Steinberg::Vst;
namespace {
struct TimedEvent { int frame; Event event; };
void require(bool ok,const char* error){if(!ok)throw std::runtime_error(error);}
void little(std::ostream& stream,uint32_t value,int bytes){for(int n=0;n<bytes;++n)stream.put(static_cast<char>((value>>(n*8))&255));}
void render(const char* plugin,const char* schedule,const char* output,int frames){
    require(frames>0 && frames<=44100*180,"frame limit");
    std::ifstream input(schedule);require(input.good(),"cannot read schedule");
    std::vector<TimedEvent> events;
    int start,end,pitch,velocity,id=0;
    while(input>>start>>end>>pitch>>velocity){
        require(start>=0 && end>start && end<=frames && pitch>=0 && pitch<=127 && velocity>=1 && velocity<=127,"bad note");
        require(id<10000,"note count limit");
        Event on{};on.type=Event::kNoteOnEvent;on.noteOn.pitch=pitch;on.noteOn.velocity=velocity/127.f;on.noteOn.noteId=id;
        Event off{};off.type=Event::kNoteOffEvent;off.noteOff.pitch=pitch;off.noteOff.noteId=id;
        events.push_back({start,on});events.push_back({end,off});++id;
    }
    require(input.eof(),"malformed schedule");
    std::stable_sort(events.begin(),events.end(),[](const auto& a,const auto& b){return a.frame<b.frame;});
    std::string error;auto module=VST3::Hosting::Module::create(plugin,error);
    require(bool(module),error.c_str());
    HostApplication host;PluginContextFactory::instance().setPluginContext(&host);
    auto factory=module->getFactory();bool rendered=false;
    for(const auto& info:factory.classInfos()){
        if(info.category()!=kVstAudioEffectClass)continue;
        PlugProvider provider(factory,info,true);require(provider.initialize(),"plugin initialization failed");
        auto component=provider.getComponentPtr();FUnknownPtr<IAudioProcessor> processor(component);
        require(bool(processor),"plugin has no audio processor");
        ProcessSetup setup{};setup.processMode=kOffline;setup.symbolicSampleSize=kSample32;setup.maxSamplesPerBlock=256;setup.sampleRate=44100;
        require(processor->setupProcessing(setup)==kResultOk,"processing setup failed");
        require(component->activateBus(kAudio,kOutput,0,true)==kResultOk,"audio output unavailable");
        require(component->activateBus(kEvent,kInput,0,true)==kResultOk,"note input unavailable");
        require(component->setActive(true)==kResultOk,"activation failed");
        require(processor->setProcessing(true)==kResultOk,"processing start failed");
        std::ofstream wav(output,std::ios::binary);require(wav.good(),"cannot write WAV");
        wav.write("RIFF",4);little(wav,36+frames*4,4);wav.write("WAVEfmt ",8);little(wav,16,4);little(wav,1,2);little(wav,2,2);little(wav,44100,4);little(wav,44100*4,4);little(wav,4,2);little(wav,16,2);wav.write("data",4);little(wav,frames*4,4);
        float left[256]{},right[256]{};float* channels[2]={left,right};AudioBusBuffers bus{};bus.numChannels=2;bus.channelBuffers32=channels;
        size_t eventIndex=0;
        for(int frame=0;frame<frames;frame+=256){
            const int count=std::min(256,frames-frame);EventList list;
            while(eventIndex<events.size() && events[eventIndex].frame<frame+count){auto event=events[eventIndex].event;event.sampleOffset=events[eventIndex].frame-frame;list.addEvent(event);++eventIndex;}
            ProcessData data{};data.processMode=kOffline;data.symbolicSampleSize=kSample32;data.numSamples=count;data.numOutputs=1;data.outputs=&bus;data.inputEvents=&list;
            require(processor->process(data)==kResultOk,"plugin processing failed");
            for(int n=0;n<count;++n)for(float* channel:channels){require(std::isfinite(channel[n]),"non-finite audio");auto pcm=static_cast<int16_t>(std::lround(std::clamp(channel[n],-1.f,1.f)*32767));little(wav,static_cast<uint16_t>(pcm),2);}
        }
        require(wav.good(),"WAV write failed");processor->setProcessing(false);component->setActive(false);rendered=true;break;
    }
    PluginContextFactory::instance().setPluginContext(nullptr);
    require(rendered,"no instrument class found");
}
}
int main(int argc,char** argv){try{if(const char* failure=std::getenv("CLARSWE_AUDIO_RENDER_ERROR");failure && std::string(failure)=="1")throw std::runtime_error("Requested renderer failure simulation");require(argc==5,"usage: clar_render plugin.vst3 notes.tsv output.wav total_frames");render(argv[1],argv[2],argv[3],std::stoi(argv[4]));return 0;}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}}
