const {chromium}=require(process.env.PLAYWRIGHT_NODE_MODULE);
(async()=>{
 const browser=await chromium.launch({headless:true,timeout:10000});
 try{
  const page=await browser.newPage();await page.goto(process.argv[2],{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelectorAll('#score ellipse').length===4,null,{timeout:10000});
  const pitches=(await page.locator('#pitch-list').textContent()).match(/[A-G](?:#|b)?-?\d+/g)||[];
  if(JSON.stringify(pitches)!==JSON.stringify(['C4','E4','G4','C5']))throw Error('Source pitches not rendered');
  await page.locator('#play').click();await page.waitForFunction(()=>document.querySelector('#recording').currentTime>.2,null,{timeout:5000});
  await page.locator('#pause').click();
  console.log('Public MIDI parse and recording playback passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
