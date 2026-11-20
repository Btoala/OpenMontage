// Execute the actual production JSX audio expressions, without launching a browser.
// Hook values are supplied by the harness; interpolate and React are real packages.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createRequire} = require('node:module');
const composer = path.resolve(__dirname, '../../remotion-composer');
const localRequire = createRequire(path.join(composer, 'package.json'));
const ts = localRequire('typescript');
const React = localRequire('react');
const {interpolate} = localRequire('remotion');

function source(name) {
  const filename = path.join(composer, 'src', name);
  return ts.createSourceFile(filename, fs.readFileSync(filename, 'utf8'),
    ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
}

function find(tree, predicate) {
  let match;
  function walk(node) {
    if (!match && predicate(node)) match = node;
    ts.forEachChild(node, walk);
  }
  walk(tree);
  if (!match) throw new Error('Production audio expression was not found');
  return match;
}

function evaluate(text, globals) {
  const js = ts.transpileModule(text, {
    compilerOptions: {jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020},
    reportDiagnostics: true,
  });
  const errors = (js.diagnostics || []).filter(d => d.category === ts.DiagnosticCategory.Error);
  if (errors.length) throw new Error(ts.formatDiagnosticsWithColorAndContext(errors, {
    getCanonicalFileName: f => f, getCurrentDirectory: () => composer, getNewLine: () => '\n',
  }));
  return vm.runInNewContext(js.outputText, globals);
}

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const state = {frame: 0};
const globals = {
  React, interpolate, Audio: 'Audio', resolveAsset: src => src,
  useCurrentFrame: () => state.frame,
  useVideoConfig: () => ({fps: input.fps, durationInFrames: input.frames}),
};
let renderAudio;
if (input.family === 'documentary-montage') {
  const tree = source('CinematicRenderer.tsx');
  const soundtrack = find(tree, n => ts.isVariableDeclaration(n) && n.name.getText(tree) === 'Soundtrack');
  globals.Soundtrack = evaluate(`(${soundtrack.initializer.getText(tree)})`, globals);
  const musicElement = find(tree, n => ts.isJsxSelfClosingElement(n)
    && n.tagName.getText(tree) === 'Soundtrack' && n.getText(tree).includes('music.src'));
  globals.music = input.music;
  renderAudio = () => globals.Soundtrack(evaluate(`(${musicElement.getText(tree)})`, globals).props);
} else {
  const tree = source('Explainer.tsx');
  const musicElement = find(tree, n => ts.isJsxSelfClosingElement(n)
    && n.tagName.getText(tree) === 'Audio' && n.getText(tree).includes('audio.music.src'));
  Object.assign(globals, {audio: {music: input.music}, fps: input.fps, durationInFrames: input.frames});
  renderAudio = () => evaluate(`(${musicElement.getText(tree)})`, globals);
}
const volumes = [];
let element;
for (state.frame = 0; state.frame < input.frames; state.frame++) {
  element = renderAudio();
  const volume = typeof element.props.volume === 'function'
    ? element.props.volume(state.frame) : element.props.volume;
  if (!Number.isFinite(volume)) throw new Error(`Invalid volume at frame ${state.frame}`);
  volumes.push(volume);
}
process.stdout.write(JSON.stringify({src: element.props.src, volumes}));
