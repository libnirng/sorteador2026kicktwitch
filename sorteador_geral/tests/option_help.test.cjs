/* Garante que as ajudas das demais abas não alteram nenhuma opção. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const code = fs.readFileSync(path.join(root, 'web/admin/js/option-help.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'web/admin/index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'web/admin/css/admin.css'), 'utf8');
assert.match(html, /option-help\.js\?v=18-context-help/);
assert.match(css, /\.has-option-help\.check/);
const ids = [...code.matchAll(/\{id:'([^']+)'/g)].map(match => match[1]);
const selectors = [...code.matchAll(/\{selector:'([^']+)'/g)].map(match => match[1]);
assert.ok(ids.length >= 48, `poucos campos: ${ids.length}`);
assert.ok(selectors.length >= 6, `poucos pontos de ajuda: ${selectors.length}`);
for (const id of ids) assert.ok(html.includes(`id="${id}"`), `campo ${id} não existe no painel`);

class Node {
  constructor(tagName='SPAN') {
    this.tagName = tagName.toUpperCase();
    this.nodeType = 1;
    this.childNodes = [];
    this.attributes = {};
    this.classNames = new Set();
    this.textContent = '';
    this.type = '';
    this.value = 'não alterar';
    this.handlers = {};
    this.classList = {
      add: name => this.classNames.add(name),
      remove: name => this.classNames.delete(name),
      contains: name => this.classNames.has(name),
      toggle: (name, on) => on ? this.classNames.add(name) : this.classNames.delete(name),
    };
  }
  set className(value) {this.classNames = new Set(value.split(/\s+/).filter(Boolean));}
  get className() {return [...this.classNames].join(' ');}
  setAttribute(name, value) {this.attributes[name] = value;}
  appendChild(item) {this.childNodes.push(item);return item;}
  append(...items) {items.forEach(item => this.appendChild(item));}
  replaceChild(next, prev) {this.childNodes.splice(this.childNodes.indexOf(prev), 1, next);}
  addEventListener(name, handler) {(this.handlers[name] ||= []).push(handler);}
  emit(name, extra={}) {
    const event = {preventDefault() {},stopPropagation() {},...extra};
    (this.handlers[name] || []).forEach(fn => fn(event));
  }
  click() {this.emit('click');}
  blur() {this.blurred = true;}
  closest(selector) {
    if (selector === 'label') return this.label || null;
    if (selector === '.switch-row') return this.switchRow || null;
    return null;
  }
  querySelector(selector) {
    if (this.switchAnchor && selector.includes('label[for]')) return this.switchAnchor;
    const matching = selector.replace(/^\./, '');
    const search = node => {
      for (const child of node.childNodes) {
        if (child.classList?.contains(matching)) return child;
        const nested = child.childNodes && search(child);
        if (nested) return nested;
      }
      return null;
    };
    return search(this);
  }
}
const switches = new Set([
  'giveaway-auto-advance','rule-viewers','rule-subs','rule-vips','rule-entry-twitch','rule-entry-kick','rule-repeat',
  'roleta-equal-slices','roleta-auto-hide','antibot-enabled','antibot-waive','antibot-send-chat',
  'ap-show_prize_list','ap-show_chances_overlay',
]);
const fields = new Map();
const anchors = new Map(selectors.map(selector => [selector, new Node('H1')]));
for (const id of ids) {
  const label = new Node('LABEL');
  label.classList.add(switches.has(id) ? 'switch' : 'check');
  const field = new Node('INPUT');
  field.label = label;
  field.type = switches.has(id) ? 'checkbox' : 'text';
  const text = {nodeType:3,textContent:id};
  label.append(text, field);
  if (switches.has(id)) {
    const row = new Node('DIV');
    row.switchAnchor = new Node('SPAN');
    row.switchAnchor.appendChild({nodeType:3,textContent:'Descrição'});
    label.switchRow = row;
  }
  fields.set(id, {label,field});
}
const docHandlers = {};
const allTips = [];
const fakeDocument = {
  createElement: name => {
    const node = new Node(name);
    if (name === 'span') allTips.push(node);
    return node;
  },
  getElementById: id => fields.get(id)?.field || null,
  querySelector: selector => anchors.get(selector) || null,
  querySelectorAll: selector => {
    assert.equal(selector, '.option-field-help.is-open');
    return allTips.filter(node => node.classList.contains('option-field-help') && node.classList.contains('is-open'));
  },
  addEventListener: (type, callback) => {docHandlers[type] = callback;},
};
vm.runInNewContext(code, {document:fakeDocument});
const tips = allTips.filter(node => node.classList.contains('option-field-help'));
assert.equal(tips.length, ids.length + selectors.length, 'nem todas as ajudas foram criadas');
for (const {field} of fields.values()) assert.equal(field.value, 'não alterar');
for (const tip of tips) {
  const trigger = tip.querySelector('.connection-help-trigger');
  assert.ok(trigger);
  assert.equal(trigger.attributes.role, 'button');
  trigger.click();
  assert.equal(trigger.attributes['aria-expanded'], 'true');
  docHandlers.click();
  assert.equal(trigger.attributes['aria-expanded'], 'false');
  trigger.emit('keydown', {key:'Enter'});
  assert.equal(trigger.attributes['aria-expanded'], 'true');
  trigger.emit('keydown', {key:'Escape'});
  assert.equal(trigger.attributes['aria-expanded'], 'false');
}
console.log(`Ajuda contextual: ${tips.length} pontos nas outras abas, controles intactos: OK`);
