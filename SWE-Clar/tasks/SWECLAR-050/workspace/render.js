export class ArenaView {
  constructor(canvas,labels) {
    this.canvas=canvas;this.labels=labels;this.yaw=.65;this.pitch=.9;this.zoom=9;this.showNames=true;
    const gl=canvas.getContext('webgl',{antialias:false,preserveDrawingBuffer:true});if(!gl)throw new Error('Prepared WebGL environment unavailable');this.gl=gl;
    const shader=(type,code)=>{const s=gl.createShader(type);gl.shaderSource(s,code);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s;};
    this.program=gl.createProgram();gl.attachShader(this.program,shader(gl.VERTEX_SHADER,'attribute vec3 p;attribute vec3 color;uniform mat4 camera;varying vec3 c;void main(){c=color;gl_Position=camera*vec4(p,1.0);}'));
    gl.attachShader(this.program,shader(gl.FRAGMENT_SHADER,'precision mediump float;varying vec3 c;void main(){gl_FragColor=vec4(c,1.0);}'));gl.linkProgram(this.program);
    if(!gl.getProgramParameter(this.program,gl.LINK_STATUS))throw new Error('Renderer link failure');gl.useProgram(this.program);
    this.buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);
    for(const [name,offset] of [['p',0],['color',12]]){const location=gl.getAttribLocation(this.program,name);gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,3,gl.FLOAT,false,24,offset);}
    gl.enable(gl.DEPTH_TEST);gl.clearColor(.055,.085,.12,1);
    canvas.addEventListener('contextmenu',e=>e.preventDefault());let dragging=false,previous;
    canvas.addEventListener('pointerdown',e=>{if(e.button===2){dragging=true;previous=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);}});
    canvas.addEventListener('pointermove',e=>{if(dragging){this.yaw+=(e.clientX-previous[0])*.01;this.pitch=Math.max(.4,Math.min(1.35,this.pitch+(e.clientY-previous[1])*.005));previous=[e.clientX,e.clientY];this.draw();}});
    canvas.addEventListener('pointerup',e=>{if(dragging){dragging=false;canvas.releasePointerCapture(e.pointerId);}});
    canvas.addEventListener('wheel',e=>{e.preventDefault();this.zoom=Math.max(5,Math.min(18,this.zoom+e.deltaY*.01));this.draw();},{passive:false});
    window.addEventListener('resize',()=>this.draw());
  }
  basis(){const s=Math.sin(this.yaw),c=Math.cos(this.yaw),p=Math.sin(this.pitch),q=Math.cos(this.pitch);return {r:[c,0,-s],u:[-s*p,q,-c*p],f:[s*q,p,c*q]};}
  project(point){
    const {r,u}=this.basis(),rect=this.canvas.getBoundingClientRect(),halfX=this.zoom*rect.width/rect.height;
    const v=[point.x,point.y||0,point.z],dot=(a)=>a.reduce((sum,n,i)=>sum+n*v[i],0);
    return {x:rect.left+(dot(r)/halfX+1)*rect.width/2,y:rect.top+(1-dot(u)/this.zoom)*rect.height/2};
  }
  ground(clientX,clientY){
    const rect=this.canvas.getBoundingClientRect(),{r,u}=this.basis();
    const x=((clientX-rect.left)/rect.width*2-1)*this.zoom*rect.width/rect.height;
    const y=(1-(clientY-rect.top)/rect.height*2)*this.zoom,det=r[0]*u[2]-r[2]*u[0];
    return {x:(x*u[2]-r[2]*y)/det,z:(r[0]*y-x*u[0])/det};
  }
  update(data){this.data=data;this.draw();}
  draw(){
    if(!this.data)return;
    const gl=this.gl,c=this.canvas,rect=c.getBoundingClientRect();c.width=Math.round(rect.width);c.height=Math.round(rect.height);gl.viewport(0,0,c.width,c.height);
    const {r,u,f}=this.basis(),sx=this.zoom*c.width/c.height,sy=this.zoom;
    gl.uniformMatrix4fv(gl.getUniformLocation(this.program,'camera'),false,new Float32Array([r[0]/sx,u[0]/sy,-f[0]/40,0,r[1]/sx,u[1]/sy,-f[1]/40,0,r[2]/sx,u[2]/sy,-f[2]/40,0,0,0,0,1]));
    const vertices=[];
    const tri=(a,b,c,color)=>{for(const v of [a,b,c])vertices.push(...v,...color);};
    const box=(x,y,z,w,h,d,color)=>{
      const p=[[-w/2,-h/2,-d/2],[w/2,-h/2,-d/2],[w/2,h/2,-d/2],[-w/2,h/2,-d/2],[-w/2,-h/2,d/2],[w/2,-h/2,d/2],[w/2,h/2,d/2],[-w/2,h/2,d/2]].map(v=>[v[0]+x,v[1]+y,v[2]+z]);
      for(const [indices,light] of [[[0,1,2,3],.72],[[5,4,7,6],.9],[[4,0,3,7],.62],[[1,5,6,2],.82],[[3,2,6,7],1],[[4,5,1,0],.5]]){
        const tint=color.map(v=>v*light),[a,b,c,d]=indices;tri(p[a],p[b],p[c],tint);tri(p[a],p[c],p[d],tint);
      }
    };
    const diamond=(x,z,color)=>{
      const ring=[[x-.4,.6,z],[x,.6,z-.4],[x+.4,.6,z],[x,.6,z+.4]];
      for(let i=0;i<4;i++){tri([x,1.5,z],ring[i],ring[(i+1)%4],color.map(v=>v*(.65+i*.1)));tri([x,0,z],ring[(i+1)%4],ring[i],color.map(v=>v*.5));}
    };
    box(0,-.12,0,16,.2,12,[.22,.31,.33]);
    for(let x=-8;x<=8;x++)box(x,.002,0,.015,.008,12,[.32,.43,.44]);
    for(let z=-6;z<=6;z++)box(0,.002,z,16,.008,.015,[.32,.43,.44]);
    const templates=new Map(this.data.config.templates.map(x=>[x.id,x]));
    const units=this.data.battle?this.data.battle.units:this.data.config.placements.map(x=>({...templates.get(x.template_id),...x,hp:templates.get(x.template_id).health}));
    for(const unit of units){
      const color=unit.hp<=0?[.32,.34,.37]:unit.team==='A'?[.18,.67,.94]:[.94,.32,.22];
      if(unit.hp<=0)box(unit.x,.15,unit.z,.8,.3,.8,color);
      else if(unit.kind==='ranged')diamond(unit.x,unit.z,color);
      else box(unit.x,.6,unit.z,.8,1.2,.8,color);
      box(unit.x,1.7,unit.z,.85,.08,.08,[.15,.16,.18]);
      if(unit.hp>0)box(unit.x-(.85-.85*unit.hp/unit.health)/2,1.7,unit.z,.85*unit.hp/unit.health,.09,.09,[.28,.88,.39]);
      const recent=this.data.battle?.events.findLast(e=>e.type==='hit'&&e.kind==='melee'&&e.attacker===unit.id&&this.data.battle.tick-e.tick<=1);
      if(recent)box(unit.x,1.35,unit.z,.25,.25,.25,[1,.9,.45]);
    }
    for(const shot of this.data.battle?.projectiles||[])box(shot.x,.8,shot.z,.18,.18,.18,[1,.86,.22]);
    gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(vertices),gl.DYNAMIC_DRAW);gl.drawArrays(gl.TRIANGLES,0,vertices.length/6);
    this.labels.replaceChildren();
    if(this.showNames)for(const unit of units){const p=this.project({x:unit.x,y:2,z:unit.z});const label=document.createElement('span');label.dataset.unit=unit.id;label.textContent=`${unit.name} · ${Math.round(unit.hp*100)/100}`;label.style.left=(p.x-rect.left)+'px';label.style.top=(p.y-rect.top)+'px';this.labels.append(label);}
  }
}
