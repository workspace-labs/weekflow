"""Exercise Layout A in installed Chrome with script execution disabled."""

from dataclasses import replace
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_weekflow import TOOL

sys.path.insert(0, str(TOOL.parent))

from weekflow_tool.meeting_design import studio_design
from weekflow_tool.page import MeetingView
from weekflow_tool.page_html import render_html


CHROME = next((str(path) for path in (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path(shutil.which("google-chrome") or "/nonexistent"),
) if path.is_file()), None)
NODE = shutil.which("node")

# Chrome's DevTools pipe needs no browser-driver package or local server.
BROWSER_CHECK = r"""
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { pathToFileURL } = require('node:url');
const [chromePath, profile, ...files] = process.argv.slice(1);
const chrome = spawn(chromePath, [
  '--headless=new', '--remote-debugging-pipe', `--user-data-dir=${profile}`,
  '--no-first-run', '--disable-background-networking', 'about:blank',
], {stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe']});
const closed = once(chrome, 'close');
let nextId = 0;
let pending = '';
const replies = new Map();
chrome.stdio[4].setEncoding('utf8');
chrome.stdio[4].on('data', chunk => {
  pending += chunk;
  while (pending.includes('\0')) {
    const end = pending.indexOf('\0');
    const reply = JSON.parse(pending.slice(0, end));
    pending = pending.slice(end + 1);
    const complete = replies.get(reply.id);
    if (complete) complete(reply);
  }
});
function request(method, params = {}, sessionId) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${method} timed out`)), 7000).unref();
    replies.set(id, reply => {
      replies.delete(id);
      clearTimeout(timer);
      if (reply.error) reject(new Error(JSON.stringify(reply.error)));
      else resolve(reply.result);
    });
    chrome.stdio[3].write(JSON.stringify({id, method, params, sessionId}) + '\0');
  });
}
function pause() {
  return new Promise(resolve => setTimeout(resolve, 40));
}
async function check(file, rtl) {
  const {targetId} = await request('Target.createTarget', {url: 'about:blank'});
  const {sessionId} = await request('Target.attachToTarget', {targetId, flatten: true});
  const send = (name, params) => request(name, params, sessionId);
  const evaluate = async expression => {
    const reply = await send('Runtime.evaluate', {expression, returnByValue: true});
    if (reply.exceptionDetails) throw new Error(JSON.stringify(reply.exceptionDetails));
    return reply.result.value;
  };
  const wait = async expression => {
    for (let attempt = 0; attempt < 60; attempt += 1) {
      if (await evaluate(expression).catch(() => false)) return;
      await pause();
    }
    throw new Error(`Could not observe ${expression}`);
  };
  const key = async (key, code, windowsVirtualKeyCode) => {
    const event = {key, code, windowsVirtualKeyCode};
    await send('Input.dispatchKeyEvent', {...event, type: 'rawKeyDown'});
    await send('Input.dispatchKeyEvent', {...event, type: 'keyUp'});
  };
  await send('Emulation.setScriptExecutionDisabled', {value: true});
  await send('Emulation.setDeviceMetricsOverride', {width: 390, height: 844, deviceScaleFactor: 1, mobile: true});
  await send('Page.navigate', {url: pathToFileURL(file).href});
  await wait(`document.readyState === 'complete' && document.querySelector('.layout-a')`);
  assert(await evaluate(`document.querySelector('#save-answers').hidden`));
  for (const link of ['current-step-1', 'step-2', 'step-3']) {
    await key('Tab', 'Tab', 9);
    assert.equal(await evaluate(`document.activeElement.id`), link);
    assert(await evaluate(`document.activeElement.matches(':focus-visible') &&
                          getComputedStyle(document.activeElement).outlineStyle !== 'none'`));
  }
  await key('Enter', 'Enter', 13);
  await wait(`location.hash === '#panel-3' && document.querySelector('#panel-3').offsetHeight > 0`);
  const move = `document.querySelector('#panel-3 .track-move').getBoundingClientRect().width`;
  assert.equal(await evaluate(move), 0);
  await key('Tab', 'Tab', 9);
  assert.equal(await evaluate(`document.activeElement.id`), 'decision-1-yes');
  await key(' ', 'Space', 32);
  await wait(`document.querySelector('#decision-1-yes').checked && ${move} > 0`);
  const reading = await evaluate(`(() => {
    const mark = name => document.querySelector('#panel-3 .dot-' + name).getBoundingClientRect().left;
    const card = getComputedStyle(document.querySelector('.decision'));
    return [mark('today'), mark('plan'), mark('now'),
            parseFloat(card.borderLeftWidth), parseFloat(card.borderRightWidth)];
  })()`);
  const [today, planned, current, leftEdge, rightEdge] = reading;
  assert(rtl ? today > planned && planned > current : today < planned && planned < current);
  assert(rtl ? rightEdge > leftEdge : leftEdge > rightEdge);
  assert(await evaluate(`document.documentElement.scrollWidth === innerWidth`));
  if (rtl) {
    const signsBeforeCount = await evaluate(`(() => {
      const count = document.querySelector('#panel-3 .label-now .live-total');
      const sign = [...count.parentNode.childNodes].find(node => node.nodeValue === '+');
      const range = document.createRange();
      range.selectNodeContents(sign);
      const beforeCount = () => range.getBoundingClientRect().left >= count.getBoundingClientRect().right;
      const plusBeforeCount = beforeCount();
      // Earlier dates are not selectable in the page. Check minus placement without changing the decision rules.
      sign.data = '-';
      range.selectNodeContents(sign);
      const minusBeforeCount = beforeCount();
      sign.data = '+';
      return [plusBeforeCount, minusBeforeCount];
    })()`);
    assert.deepEqual(signsBeforeCount, [true, true], 'Arabic caption signs must render before the day count');
  }
  await key('ArrowRight', 'ArrowRight', 39);
  await wait(`!document.querySelector('#decision-1-yes').checked && ${move} === 0`);
  await request('Target.closeTarget', {targetId});
}
(async () => {
  try {
    const launched = await Promise.race([
      request('Browser.getVersion').then(() => true), closed.then(() => false),
    ]);
    if (!launched) {
      console.error('Installed Chrome could not start in this test environment');
      process.exitCode = 77;
      return;
    }
    await check(files[0], false);
    await check(files[1], true);
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  } finally {
    if (chrome.exitCode === null && chrome.signalCode === null) {
      await request('Browser.close').catch(() => chrome.kill());
    }
    await closed;
  }
})();
"""


def page_for(language):
    names = {"en": ("Corner Bakery", "The menu is ready", "Offer a later pickup", "The shop stays open"),
             "ar": ("مخبز الحي", "القائمة جاهزة", "موعد استلام إضافي", "المخبز مفتوح مساءً")}
    project, headline, decision, reason = names[language]
    delivery = "2026-03-12"
    view = MeetingView(
        {"project": project, "language": language, "client": "", "attendees": [],
         "planned_end": delivery, "scope_approved_on": "2026-02-01"},
        {"number": 1, "meeting_date": "2026-02-26", "mode": "build", "held": False,
         "end_before": delivery},
        {"headline": headline, "finished": [], "next_week": [], "needs": []},
        [{"id": "C-001", "what": decision, "reason": reason, "date": "2026-02-25",
          "asked_by": project, "days_added": 2}],
        [], design=replace(studio_design(language), page_layout="a"),
    )
    return render_html(view)


@unittest.skipUnless(NODE and CHROME, "Installed Chrome and Node.js are required for the browser check")
class LayoutABrowserTests(unittest.TestCase):
    def test_keyboard_and_delivery_preview_work_without_script_in_both_directions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pages = []
            for language in ("en", "ar"):
                page = root / f"meeting-{language}.html"
                page.write_text(page_for(language), encoding="utf-8")
                pages.append(str(page))
            result = subprocess.run(
                [NODE, "-e", BROWSER_CHECK, CHROME, str(root / "chrome"), *pages],
                capture_output=True, text=True, timeout=45,
            )
        if result.returncode == 77:
            self.skipTest(result.stderr.strip())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
