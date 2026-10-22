const fs=require('fs');const {chromium}=require(process.env.PLAYWRIGHT_NODE_MODULE||'/usr/local/lib/python3.12/dist-packages/playwright/driver/package');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.UI_BROWSER_WRAPPER,env:{PATH:process.env.PATH,HOME:process.env.UI_BROWSER_HOME,ARENA_BROWSER_BINARY:chromium.executablePath()}});const page=await browser.newPage({viewport:{width:900,height:900}});page.setDefaultTimeout(6000);const errors=[],remote=[];page.on('pageerror',e=>errors.push(String(e)));await page.route('**/*',r=>{if(r.request().url().startsWith(process.argv[2]))return r.continue();remote.push(r.request().url());return r.abort();});const t=id=>page.getByTestId(id);const report={};const gate=Number(process.argv[6]);
try{
 await page.goto(process.argv[2]);await t('screen-home').waitFor();report.rendered=await t('slider').isVisible();
 if(gate===2){
 await t('tab-saved').click();report.saved=await t('screen-saved').isVisible();await t('unknown-route').click();report.unknown=(await t('route-error').textContent())==='unknown_route'&&await t('screen-saved').isVisible();
 await page.route('**/config.json',async route=>{const response=await route.fetch();const config=await response.json();config.authenticated=false;await route.fulfill({json:config});});await page.reload();await t('screen-home').waitFor();await t('tab-profile').click();report.guard=(await t('route-error').textContent())==='auth_required'&&await t('screen-home').isVisible();
 }
 if(gate===3){
 const checkbox=page.getByRole('checkbox',{name:/Open now/i});
 await t('tab-home').click();await t('filter-label').getByText('Open now',{exact:false}).click();report.label=await checkbox.isChecked();await t('filter-box').click();report.box=!(await checkbox.isChecked());report.rating=await t('rating').textContent();
 }
 if(gate===4){
 report.rating=await t('rating').textContent();
 const scroll=t('content-scroll'),slider=t('slider');const box=await slider.boundingBox();const x=box.x+box.width*.35,y=box.y+box.height/2;const start=await t('slider-thumb').boundingBox();const radiusBefore=Number.parseFloat(await t('slider-value').textContent());
 await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+box.width*.15,y,{steps:8});await page.waitForTimeout(80);const end=await t('slider-thumb').boundingBox();report.moved=(end.x-start.x)/box.width;report.radiusBefore=radiusBefore;report.radiusAfter=Number.parseFloat(await t('slider-value').textContent());const before=await scroll.evaluate(e=>e.scrollTop);await page.mouse.wheel(0,180);await page.waitForTimeout(180);report.locked=(await scroll.evaluate(e=>e.scrollTop))===before;await page.mouse.up();await page.mouse.wheel(0,180);await page.waitForTimeout(180);report.restored=(await scroll.evaluate(e=>e.scrollTop))>before;
 await scroll.evaluate(e=>{e.scrollTop=0;});await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+20,y,{steps:2});await page.evaluate(()=>window.dispatchEvent(new Event('blur')));await page.mouse.up();await page.mouse.wheel(0,120);await page.waitForTimeout(180);report.cancelled=(await scroll.evaluate(e=>e.scrollTop))>0;
 report.ratingCases=[];
 for(const rating of [4,0,2.34]){
  await page.route('**/config.json',async route=>{const response=await route.fetch();const config=await response.json();config.rating=rating;await route.fulfill({json:config});});
  await page.reload();await t('screen-home').waitFor();report.ratingCases.push(await t('rating').textContent());
  await page.unroute('**/config.json');
 }

 }
 if(gate===5){
 const inspectImage=async uri=>await page.evaluate(async uri=>{
  const response=await fetch(uri);const blob=await response.blob();const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(blob);});
  const image=await createImageBitmap(blob);const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;const context=canvas.getContext('2d');context.drawImage(image,0,0);const bytes=context.getImageData(0,0,image.width,image.height).data;const rgba=btoa(String.fromCharCode(...bytes));const size=[image.width,image.height];image.close();return {encoded,rgba,size};
 },uri);
 await t('tab-profile').click();await t('facility-image').waitFor();const imageData=async id=>t(id).evaluate(e=>{const im=e.tagName==='IMG'?e:e.querySelector('img');return im?.src;});const account=await imageData('account-image'),prior=await imageData('facility-image');
 await t('image-picker').setInputFiles({name:'synthetic.png',mimeType:'image/png',buffer:fs.readFileSync(process.argv[3])});await page.waitForTimeout(200);report.image=await imageData('facility-image');const firstPixels=await inspectImage(report.image);report.changed=report.image!==prior;report.accountSame=(await imageData('account-image'))===account;
 await t('image-picker').setInputFiles({name:'corrupt.png',mimeType:'image/png',buffer:Buffer.from('not a valid image')});await page.waitForTimeout(120);report.corrupt=(await t('image-error').textContent())==='unsupported_asset'&&(await imageData('facility-image'))===report.image;
 await t('image-picker').setInputFiles({name:'unsupported.txt',mimeType:'text/plain',buffer:Buffer.from('not an image')});await page.waitForTimeout(80);report.unsupported=(await t('image-error').textContent())==='unsupported_asset'&&(await imageData('facility-image'))===report.image;
 await t('image-picker').setInputFiles([]);report.cancelPreserves=(await imageData('facility-image'))===report.image;
 // Delay real native image decoding for the first selection; second must win.
 await page.evaluate(()=>{const native=HTMLImageElement.prototype.decode,bitmap=window.createImageBitmap;let calls=0;const delay=p=>++calls===1?p.then(value=>new Promise(r=>setTimeout(()=>r(value),250))):p;HTMLImageElement.prototype.decode=function(){return delay(native.call(this));};window.createImageBitmap=function(...args){return delay(bitmap.apply(this,args));};});
 await t('image-picker').setInputFiles({name:'first.png',mimeType:'image/png',buffer:fs.readFileSync(process.argv[3])});await t('image-picker').setInputFiles({name:'second.png',mimeType:'image/png',buffer:fs.readFileSync(process.argv[4])});await page.waitForTimeout(450);report.latestImage=await imageData('facility-image');const latestPixels=await inspectImage(report.latestImage);

 const beforeJpeg=await imageData('facility-image');
 await t('image-picker').setInputFiles({name:'sample.jpg',mimeType:'image/jpeg',buffer:fs.readFileSync(process.argv[5])});
 await page.waitForFunction(before=>{const e=document.querySelector('[data-testid="facility-image"]');const im=e.tagName==='IMG'?e:e.querySelector('img');return im&&im.src!==before&&im.complete&&im.naturalWidth>0;},beforeJpeg);
 report.jpegImage=await imageData('facility-image');const jpegPixels=await inspectImage(report.jpegImage);report.accountSame=report.accountSame&&(await imageData('account-image'))===account;

 const resourcePrior=await imageData('facility-image');
 report.resourceRejected=[];
 for(const [name,buffer] of [['large.png',fs.readFileSync(process.argv[3]+'-oversize')],['wide.png',fs.readFileSync(process.argv[3]+'-wide')]]){
  await t('image-picker').setInputFiles({name,mimeType:'image/png',buffer});
  await page.waitForFunction(()=>document.querySelector('[data-testid="image-error"]').textContent==='unsupported_asset');
  await page.waitForTimeout(350);report.resourceRejected.push((await imageData('facility-image'))===resourcePrior);
 }
 // Snapshots were captured while each selected Blob URL was still live.
 report.image=firstPixels;report.latestImage=latestPixels;report.jpegImage=jpegPixels;

 report.resourceAccepted=[];
 for(const suffix of ['-edge','-size-edge']){
  const prior=await imageData('facility-image');
  await t('image-picker').setInputFiles({name:'boundary.png',mimeType:'image/png',buffer:fs.readFileSync(process.argv[3]+suffix)});
  await page.waitForFunction(prior=>{const e=document.querySelector('[data-testid="facility-image"]');const im=e.tagName==='IMG'?e:e.querySelector('img');return im&&im.src!==prior&&im.complete&&im.naturalWidth>0&&document.querySelector('[data-testid="image-error"]').textContent==='';},prior);
  report.resourceAccepted.push((await imageData('account-image'))===account);
 }

 }
 report.errors=errors;report.remote=remote;console.log(JSON.stringify(report));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
