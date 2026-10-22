const {chromium,firefox}=require(process.env.PLAYWRIGHT_NODE_MODULE || 'playwright');
(async()=>{
  const engine=process.platform==='linux'?firefox:chromium;
  const options={headless:true,downloadsPath:process.env.STREAM_BROWSER_HOME,
    env:{PATH:process.env.PATH,HOME:process.env.STREAM_BROWSER_HOME,ARENA_BROWSER_BINARY:engine.executablePath()}};
  if(process.platform==='linux') options.executablePath=process.env.STREAM_BROWSER_WRAPPER;
  else if(process.env.STREAM_BROWSER_BINARY) options.executablePath=process.env.STREAM_BROWSER_BINARY;
  if(process.platform==='linux'&&!options.executablePath)throw Error('Protected browser launcher missing');
  const browser=await engine.launch(options);
  try{
    const context=await browser.newContext();
    await context.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
    const page=await context.newPage();
    await page.goto(process.argv[2]);
    await page.locator('input[type="search"]').fill('synthetic-index');
    await page.locator('form').first().evaluate(f=>f.requestSubmit());
    await page.getByRole('button',{name:'Synthetic recording',exact:true}).click();
    const video=page.locator('video').first();
    const count=process.argv[3]==='count';
    const counted=count?page.waitForResponse(r=>r.url()===process.argv[2]+'/view'&&r.request().method()==='POST',{timeout:8000}):null;
    if(counted) counted.catch(()=>{}); // Preserve the playback error if playback fails first.
    await video.evaluate(v=>{v.muted=true;return v.play();});
    await page.waitForFunction(()=>{const v=document.querySelector('video');return v&&v.currentTime>.6&&v.videoWidth>0;});
    const before=await video.evaluate(v=>v.currentTime);
    await page.waitForFunction(t=>document.querySelector('video').currentTime>t+.5,before);
    const playback=await video.evaluate(v=>({time:v.currentTime,width:v.videoWidth,height:v.videoHeight,frames:v.getVideoPlaybackQuality().totalVideoFrames}));
    if(playback.frames<5)throw Error('Archive frames did not decode');
    if(count){const response=await counted;if(response.status()!==200)throw Error('Playback count rejected');}
    console.log(JSON.stringify({passed:true,playback,playback_count_observed:count}));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
