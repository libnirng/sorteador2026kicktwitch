/* Verifica a ajuda visual das conexões sem acessar tokens, rede ou servidor. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'web/admin/index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'web/admin/css/admin.css'), 'utf8');
const js = fs.readFileSync(path.join(root, 'web/admin/js/connection-help.js'), 'utf8');
assert.match(html, /connection-help\.js\?v=17-connection-help/);
assert.match(css, /\.connection-field-help:where\(:hover,:focus-within,\.is-open\)/);

class FakeNode {
  constructor(tagName = 'span') {
    this.tagName = tagName;
    this.nodeType = 1;
    this.childNodes = [];
    this.attributes = {};
    this.handlers = {};
    this.className = '';
    this.textContent = '';
    this.type = '';
    this.value = '';
    this.parentElement = null;
    this.classList = {
      contains: name => this.className.split(/\s+/).includes(name),
      add: name => { if (!this.classList.contains(name)) this.className += ` ${name}`; },
      remove: name => { this.className = this.className.split(/\s+/).filter(x => x !== name).join(' '); },
      toggle: (name, on) => on ? this.classList.add(name) : this.classList.remove(name),
    };
  }
  setAttribute(key, value) { this.attributes[key] = value; }
  appendChild(node) { this.childNodes.push(node); node.parentElement = this; return node; }
  append(...nodes) { nodes.forEach(node => this.appendChild(node)); }
  replaceChild(newChild, oldChild) {
    const index = this.childNodes.indexOf(oldChild);
    assert.ok(index >= 0);
    this.childNodes[index] = newChild;
    newChild.parentElement = this;
  }
  addEventListener(type, handler) { (this.handlers[type] ||= []).push(handler); }
  emit(type, extra = {}) {
    const event = {preventDefault() {}, stopPropagation() {}, ...extra};
    (this.handlers[type] || []).forEach(handler => handler(event));
  }
  click() { this.emit('click'); }
  blur() { this.blurred = true; }
  closest(selector) {
    if (selector === 'label') return this.label || null;
    if (selector === '[data-panel="connections"]') return true;
    return null;
  }
  querySelector(selector) {
    if (selector === '.connection-help-trigger') return this.childNodes.find(node => node.classList?.contains('connection-help-trigger')) || null;
    return null;
  }
}

const fields = new Map();
const boxes = new Set(['bot-send-twitch', 'bot-send-kick', 'kick-receive-autostart', 'megamu-enabled', 'env-real-mode']);
const ids = [
  'twitch-channel', 'twitch-client-id', 'twitch-helix-token',
  'kick-receive-channel', 'kick-receive-mode', 'kick-receive-room', 'kick-receive-channel-id',
  'kick-client-id', 'kick-redirect-uri', 'kick-client-secret',
  'megamu-dv', 'megamu-key', ...boxes,
];
for (const id of ids) {
  const label = new FakeNode('label');
  const input = new FakeNode('input');
  input.type = boxes.has(id) ? 'checkbox' : 'text';
  input.value = 'valor-anterior';
  input.label = label;
  const title = {nodeType: 3, textContent: id};
  if (boxes.has(id)) label.append(input, title);
  else label.append(title, input);
  fields.set(id, {input, label});
}
const documentHandlers = {};
const fakeDocument = {
  getElementById: id => fields.get(id)?.input || null,
  createElement: tag => new FakeNode(tag),
  addEventListener: (name, fn) => { documentHandlers[name] = fn; },
  querySelectorAll: selector => {
    assert.equal(selector, '.connection-field-help.is-open');
    return [...fields.values()].flatMap(({label}) => {
      const help = label.childNodes.flatMap(node => node.childNodes || []).find(node => node.classList?.contains('connection-field-help')) ||
        label.childNodes.find(node => node.classList?.contains('connection-field-help'));
      return help?.classList.contains('is-open') ? [help] : [];
    });
  },
};
vm.runInNewContext(js, {document: fakeDocument});

for (const id of ids) {
  const {input, label} = fields.get(id);
  assert.equal(input.value, 'valor-anterior', `valor de ${id} alterado`);
  const parent = boxes.has(id) ? label : label.childNodes[0];
  const help = parent.childNodes.find(node => node.classList?.contains('connection-field-help'));
  assert.ok(help, `faltou ? em ${id}`);
  const trigger = help.querySelector('.connection-help-trigger');
  assert.ok(trigger, `faltou controle de ajuda em ${id}`);
  assert.equal(trigger.attributes.role, 'button');
  assert.equal(trigger.attributes.tabindex, '0');
  assert.match(trigger.attributes['aria-label'], /Como obter ou configurar/);
  const popup = help.childNodes.find(node => node.classList.contains('connection-help-popup'));
  assert.equal(popup.attributes.role, 'tooltip');
  assert.ok(popup.childNodes.some(node => node.tagName === 'ol'), `faltaram instruções em ${id}`);
  trigger.click();
  assert.ok(help.classList.contains('is-open'), `não abriu ${id}`);
  assert.equal(trigger.attributes['aria-expanded'], 'true');
  documentHandlers.click();
  assert.ok(!help.classList.contains('is-open'), `não fechou ${id}`);
  trigger.emit('keydown', {key: 'Enter'});
  assert.ok(help.classList.contains('is-open'), `teclado não abriu ${id}`);
  trigger.emit('keydown', {key: 'Escape'});
  assert.ok(!help.classList.contains('is-open'), `Escape não fechou ${id}`);
}
console.log(`Conexões: ${ids.length} ajudas, interação e campos preservados: OK`);
