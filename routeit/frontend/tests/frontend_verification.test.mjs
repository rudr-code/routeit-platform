import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, '..');

function runFrontendTests() {
  console.log('Running Route.it Frontend Verification Suite...');

  const requiredFiles = [
    'package.json',
    'tsconfig.json',
    'vite.config.ts',
    'index.html',
    'src/main.tsx',
    'src/App.tsx',
    'src/components/InteractiveMap.tsx',
    'src/api/client.ts',
    'src/types/api.ts',
    'src/styles/enterprise.css',
  ];

  for (const rel of requiredFiles) {
    const full = path.join(frontendRoot, rel);
    assert.ok(fs.existsSync(full), `Missing required frontend file: ${rel}`);
    const stat = fs.statSync(full);
    assert.ok(stat.size > 50, `Frontend file ${rel} is unexpectedly empty`);
  }

  const appSource = fs.readFileSync(path.join(frontendRoot, 'src/App.tsx'), 'utf-8');
  for (const tab of [
    'dashboard',
    'depot',
    'orders',
    'fleet',
    'planning',
    'results',
    'replan',
    'benchmarks',
  ]) {
    assert.ok(appSource.includes(`'${tab}'`), `App.tsx missing workflow tab: ${tab}`);
  }
  assert.ok(
    appSource.includes('showAdvancedControls'),
    'App.tsx must implement progressive disclosure for advanced research parameters'
  );
  assert.ok(
    appSource.includes('hasFixedTimeWindow') && appSource.includes('type="time"'),
    'App.tsx must support optional fixed time windows with HH:MM time pickers'
  );
  assert.ok(
    appSource.includes('handleSaveEditedOrder') && appSource.includes('showToast'),
    'App.tsx must support editing existing orders and displaying confirmation toast popups'
  );

  const mapSource = fs.readFileSync(path.join(frontendRoot, 'src/components/InteractiveMap.tsx'), 'utf-8');
  assert.ok(mapSource.includes('onSelectLocation'), 'InteractiveMap must support click/pin selection');
  assert.ok(
    mapSource.includes('base-satellite-layer') && mapSource.includes('base-hybrid-labels-layer'),
    'InteractiveMap must support unified multi-layer Street, Satellite, Hybrid, and Terrain switching'
  );

  const cssSource = fs.readFileSync(path.join(frontendRoot, 'src/styles/enterprise.css'), 'utf-8');
  assert.ok(cssSource.includes('--bg-app: #f7f4ed'), 'CSS must use warm sand background');
  assert.ok(cssSource.includes('--obsidian: #1c1d1a'), 'CSS must use dark obsidian navigation theme');

  console.log('All Frontend verification suites passed!');
}

runFrontendTests();
