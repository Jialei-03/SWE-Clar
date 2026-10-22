class WebPlayer {
 constructor(){this.audio=new Audio();this.audio.dataset.player='practice';this.audio.hidden=true;document.body.append(this.audio);this.url=null;this.generation=0;}
 async play(track,origin,token){const request=++this.generation;const response=await fetch(origin+'/audio/'+encodeURIComponent(track.id),{headers:{Authorization:'Bearer '+token}});if(!response.ok)throw Error('audio_unavailable');const blob=await response.blob();if(request!==this.generation)return;this.audio.pause();if(this.url)URL.revokeObjectURL(this.url);this.url=URL.createObjectURL(blob);this.audio.src=this.url;await this.audio.play();}
 async pause(){this.generation++;this.audio.pause();}
 async resume(){await this.audio.play();}
 async snapshot(){return {position:this.audio.currentTime,isPlaying:!this.audio.paused&&!this.audio.ended};}
 async clear(){this.generation++;this.audio.pause();this.audio.removeAttribute('src');this.audio.load();if(this.url)URL.revokeObjectURL(this.url);this.url=null;}
}
export const player=new WebPlayer();
