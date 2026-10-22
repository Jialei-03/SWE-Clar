// Independently authored deterministic test instrument; no recordings or customer assets.
#include "public.sdk/source/vst/vstaudioeffect.h"
#include "public.sdk/source/vst/vsteditcontroller.h"
#include "public.sdk/source/main/pluginfactory.h"
#include "pluginterfaces/vst/ivstevents.h"
#include "pluginterfaces/vst/vstspeaker.h"
#include <algorithm>
#include <cmath>
#include <vector>
using namespace Steinberg;
using namespace Steinberg::Vst;
namespace {
const FUID controllerId(0x78315BAC,0x914248ED,0xA9E6C14B,0x5F3077D2);
class Controller final: public EditController {
public:
    static FUnknown* create(void*) { return static_cast<IEditController*>(new Controller); }
};
struct Voice { int id; int pitch; double velocity; double age=0; double released=-1; };
class Piano final: public AudioEffect {
    std::vector<Voice> voices;
    bool running=false;
public:
    Piano() { setControllerClass(controllerId); }
    static FUnknown* create(void*) { return static_cast<IAudioProcessor*>(new Piano); }
    tresult PLUGIN_API initialize(FUnknown* context) override {
        auto rc=AudioEffect::initialize(context);
        if(rc!=kResultOk)return rc;
        addEventInput(STR16("Notes"),1);
        addAudioOutput(STR16("Stereo"),SpeakerArr::kStereo);
        return kResultOk;
    }
    tresult PLUGIN_API setActive(TBool active) override {
        voices.clear();return AudioEffect::setActive(active);
    }
    tresult PLUGIN_API setProcessing(TBool enabled) override {
        running=enabled;voices.clear();return kResultOk;
    }
    tresult PLUGIN_API process(ProcessData& data) override {
        if(!running)return kResultFalse;
        if(data.symbolicSampleSize!=kSample32 || data.numOutputs!=1 || data.outputs[0].numChannels!=2)return kInvalidArgument;
        const double rate=processSetup.sampleRate;
        int eventIndex=0;
        const int eventCount=data.inputEvents?data.inputEvents->getEventCount():0;
        for(int sample=0;sample<data.numSamples;++sample){
            while(eventIndex<eventCount){
                Event e{};if(data.inputEvents->getEvent(eventIndex,e)!=kResultOk)return kInvalidArgument;
                if(e.sampleOffset>sample)break;
                ++eventIndex;
                if(e.type==Event::kNoteOnEvent && e.noteOn.velocity>0){
                    if(voices.size()<256)voices.push_back({e.noteOn.noteId,e.noteOn.pitch,e.noteOn.velocity});
                }else if(e.type==Event::kNoteOffEvent){
                    for(auto& v:voices)if(v.id==e.noteOff.noteId && v.released<0)v.released=v.age;
                }
            }
            double value=0;
            for(auto& v:voices){
                const double frequency=440*std::pow(2.0,(v.pitch-69)/12.0);
                const double phase=2*3.14159265358979323846*frequency*v.age;
                const double attack=std::min(1.0,v.age/.006);
                const double release=v.released<0?1.0:std::max(0.0,1-(v.age-v.released)/.25);
                const double decay=std::exp(-v.age/1.8);
                value+=v.velocity*attack*release*decay*(std::sin(phase)+.22*std::sin(2*phase)+.08*std::sin(3*phase))*.22;
                v.age+=1/rate;
            }
            voices.erase(std::remove_if(voices.begin(),voices.end(),[](const Voice& v){return v.released>=0 && v.age-v.released>.25;}),voices.end());
            const float x=static_cast<float>(std::tanh(value));
            data.outputs[0].channelBuffers32[0][sample]=x;
            data.outputs[0].channelBuffers32[1][sample]=x;
        }
        data.outputs[0].silenceFlags=0;
        return kResultOk;
    }
};
}
bool InitModule(){return true;}
bool DeinitModule(){return true;}
BEGIN_FACTORY("Clar-SWE", "https://example.test", "", PFactoryInfo::kNoFlags)
DEF_CLASS2(INLINE_UID(0x78315BAC,0x914248ED,0xA9E6C14B,0x5F3077D1),PClassInfo::kManyInstances,kVstAudioEffectClass,"Clar Piano",0,"Instrument|Synth","1.0.0",kVstVersionString,Piano::create)
DEF_CLASS2(INLINE_UID(0x78315BAC,0x914248ED,0xA9E6C14B,0x5F3077D2),PClassInfo::kManyInstances,kVstComponentControllerClass,"Clar Piano Controller",0,"","1.0.0",kVstVersionString,Controller::create)
END_FACTORY
