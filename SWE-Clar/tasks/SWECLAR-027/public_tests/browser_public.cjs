const {chromium}=require(process.env.PLAYWRIGHT_NODE_MODULE||'/usr/local/lib/python3.12/dist-packages/playwright/driver/package');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.UI_BROWSER_WRAPPER,env:{PATH:process.env.PATH,HOME:process.env.UI_BROWSER_HOME,ARENA_BROWSER_BINARY:chromium.executablePath()}});
 try{
  const page=await browser.newPage();await page.route('**/*',r=>r.request().url().startsWith(process.argv[2])?r.continue():r.abort());
  await page.goto(process.argv[2]);await page.getByTestId('screen-home').waitFor();
  await page.getByTestId('tab-saved').click();await page.getByTestId('screen-saved').waitFor();
  await page.getByTestId('unknown-route').click();
  if(await page.getByTestId('route-error').textContent()!=='unknown_route')throw Error('Unknown route response missing');
  if(!await page.getByTestId('screen-saved').isVisible())throw Error('Unknown route replaced current screen');
  console.log(JSON.stringify({passed:true,real_navigation:true,unknown_route_preserved:true}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
