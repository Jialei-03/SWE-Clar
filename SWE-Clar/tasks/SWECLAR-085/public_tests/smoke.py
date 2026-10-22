from support import application,play
with application() as page:
    play(page)
    assert page.locator('audio').evaluate('(a)=>a.readyState>=2 && a.currentTime>0')
    page.locator('#pause').click()
    assert page.locator('audio').evaluate('(a)=>a.paused')
print('Real Chromium audio and HTTP programme smoke passed')
