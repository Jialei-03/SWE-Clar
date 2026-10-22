import React,{useState,useRef,useEffect} from 'react';
import {View,Text,Pressable,ScrollView,Image,PanResponder,StyleSheet} from 'react-native';
import {transition,displayRating} from './model';
import {decodeImage} from './image';
export default function App({config}) {
 const [state,setState]=useState({route:config.routes[0],openNow:false,error:''});
 const [dragging,setDragging]=useState(false),[slider,setSlider]=useState(35);
 const [facilityImage,setFacilityImage]=useState(config.facilityImage),[imageError,setImageError]=useState('');
 const width=useRef(1),start=useRef(0),value=useRef(35),imageEpoch=useRef(0);
 const event=e=>setState(old=>transition(old,e,config));
 const update=v=>{value.current=Math.max(0,Math.min(100,v));setSlider(value.current);};
 const responder=useRef(PanResponder.create({onStartShouldSetPanResponder:()=>true,
  onPanResponderGrant:()=>{start.current=value.current;setDragging(true);},
  onPanResponderMove:(_e,g)=>update(start.current+g.dx/width.current*100),
  onPanResponderRelease:()=>setDragging(false),onPanResponderTerminate:()=>setDragging(false),
  onPanResponderTerminationRequest:()=>true})).current;
 useEffect(()=>{const lost=()=>setDragging(false);window.addEventListener('blur',lost);return()=>{window.removeEventListener('blur',lost);imageEpoch.current++;};},[]);
 async function select(e){const file=e.target.files?.[0];e.target.value='';if(!file)return;const epoch=++imageEpoch.current;
  try{const data=await decodeImage(file);if(epoch!==imageEpoch.current)return;throw new Error('Image selection not connected');setImageError('');}
  catch{if(epoch===imageEpoch.current)setImageError('unsupported_asset');}}
 return <View style={styles.shell}>
  <Text role="heading" aria-level={1} style={styles.title}>Field notebook</Text>
  <Text style={styles.subtitle}>Independent navigation and interaction fixture</Text>
  <View style={styles.tabs}>{config.routes.map(route=><Pressable key={route} testID={'tab-'+route} accessibilityRole="button" onPress={()=>event({type:'navigate',route})} style={[styles.tab,state.route===route&&styles.active]}><Text>{route}</Text></Pressable>)}
  <Pressable testID="unknown-route" accessibilityRole="button" onPress={()=>event({type:'navigate',route:'missing'})} style={styles.tab}><Text>Test missing route</Text></Pressable></View>
  <Text testID="route-error" accessibilityRole="alert">{state.error}</Text>
  <ScrollView testID="content-scroll" style={styles.scroll} scrollEnabled={true} contentContainerStyle={styles.content}>
   <View testID={'screen-'+state.route}>
   <Text accessibilityRole="header" style={styles.heading}>{state.route==='home'?'Discover places':state.route==='saved'?'Saved places':'Facility profile'}</Text>
   {state.route==='home'&&<>
    <Pressable testID="filter-label" accessibilityRole="checkbox" aria-checked={state.openNow} onPress={()=>event({type:'toggle_filter'})} style={styles.filter}>
     <View testID="filter-box" style={[styles.box,state.openNow&&styles.checked]}><Text>{state.openNow?'✓':''}</Text></View><Text>Open now — include currently available places</Text>
    </Pressable>
    <View style={styles.card}><Text style={styles.heading}>{config.placeName}</Text><Text testID="rating" style={styles.rating}>{displayRating(config.rating)}</Text><Text>Visitor rating</Text></View>
    <Text style={styles.label}>Search radius</Text>
    <View testID="slider" {...responder.panHandlers} onLayout={e=>{width.current=e.nativeEvent.layout.width;}} style={styles.slider}>
     <View style={styles.rail}/><View testID="slider-thumb" style={[styles.thumb,{left:slider+'%'}]}/>
    </View><Text testID="slider-value">{Math.round(slider)} km</Text>
    {Array.from({length:14},(_,i)=><View key={i} style={styles.row}><Text>Sample place {i+1}</Text><Text>Generated local listing</Text></View>)}
   </>}
   {state.route==='saved'&&<Text>No saved places in this fixture.</Text>}
   {state.route==='profile'&&<><Text>Facility image</Text><Image testID="facility-image" source={{uri:facilityImage}} style={styles.photo}/>
    <label style={{display:'block',margin:'16px 0'}}>Select facility image<input data-testid="image-picker" type="file" accept="image/png,image/jpeg" onChange={select} style={{display:'block',maxWidth:'100%',marginTop:10}}/></label>
    <Text testID="image-error" accessibilityRole="alert">{imageError}</Text><Text>Account avatar</Text><Image testID="account-image" source={{uri:config.accountImage}} style={styles.avatar}/></>}
   </View>
  </ScrollView>
 </View>;
}
const styles=StyleSheet.create({shell:{maxWidth:760,width:'100%',alignSelf:'center',padding:24},title:{fontSize:30,fontWeight:'700',color:'#173e48'},subtitle:{color:'#577179',marginTop:8,marginBottom:24},tabs:{flexDirection:'row',flexWrap:'wrap',gap:8},tab:{padding:12,backgroundColor:'#e6eeef',borderRadius:7},active:{backgroundColor:'#a9d8d0'},scroll:{height:550,flexGrow:0,marginTop:18,borderWidth:1,borderColor:'#cadbde',borderRadius:8},content:{padding:20},heading:{fontSize:22,fontWeight:'600',marginBottom:16},filter:{flexDirection:'row',alignItems:'center',gap:12,paddingVertical:14,flexWrap:'wrap'},box:{height:24,width:24,borderWidth:2,borderColor:'#42796f',alignItems:'center',justifyContent:'center'},checked:{backgroundColor:'#a9d8d0'},card:{padding:20,backgroundColor:'#f0f6f5',borderRadius:8,marginVertical:14},rating:{fontSize:32,color:'#256258'},label:{fontSize:17,marginVertical:12},slider:{height:44,marginHorizontal:12,touchAction:'none'},rail:{position:'absolute',top:19,left:0,right:0,height:6,borderRadius:3,backgroundColor:'#d2e4df'},thumb:{position:'absolute',top:9,width:26,height:26,marginLeft:-13,borderRadius:13,backgroundColor:'#31786b'},row:{paddingVertical:22,borderBottomWidth:1,borderColor:'#e0e9e9',gap:6},photo:{width:220,height:150,resizeMode:'contain',backgroundColor:'#edf2f2'},avatar:{width:80,height:80,resizeMode:'contain'}});
