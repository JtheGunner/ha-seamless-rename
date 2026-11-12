// A very small DOM, just enough for the panel component: elements, text, attributes,
// listeners and `[data-test="x"]` / tag selectors. It is not a browser.

class FakeText {
  constructor(text) {
    this.text = String(text);
  }
  get textContent() {
    return this.text;
  }
}

const toNode = (node) => (node instanceof FakeElement || node instanceof FakeText ? node : new FakeText(node));

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.attributes = {};
    this.children = [];
    this.listeners = {};
    this.className = "";
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this._text = null;
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }
  getAttribute(name) {
    return this.attributes[name] ?? null;
  }
  // Like a browser, anything that is not a node is converted to a text node (null → "null").
  append(...nodes) {
    this.children.push(...nodes.map(toNode));
  }
  replaceChildren(...nodes) {
    this.children = nodes.map(toNode);
    this._text = null;
  }
  addEventListener(type, listener) {
    (this.listeners[type] ??= []).push(listener);
  }
  get textContent() {
    return this._text ?? this.children.map((child) => child.textContent).join("");
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  /** Fire an event; ``init`` may override ``target`` fields such as ``value`` or ``checked``. */
  async fire(type, init = {}) {
    Object.assign(this, init);
    for (const listener of this.listeners[type] ?? []) {
      await listener({ type, target: this });
    }
  }
  matches(selector) {
    const attribute = /^\[([\w-]+)="([^"]*)"\]$/.exec(selector);
    if (attribute) return this.attributes[attribute[1]] === attribute[2];
    return this.tagName === selector.toUpperCase();
  }
  querySelectorAll(selector) {
    const found = [];
    for (const child of this.children) {
      if (!(child instanceof FakeElement)) continue;
      if (child.matches(selector)) found.push(child);
      found.push(...child.querySelectorAll(selector));
    }
    return found;
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] ?? null;
  }
}

class FakeHTMLElement extends FakeElement {
  constructor() {
    super("custom-element");
  }
}

/** Install the globals the component expects. Call once before importing it. */
export function installDom() {
  const registry = new Map();
  globalThis.HTMLElement = FakeHTMLElement;
  globalThis.document = {
    createElement: (tag) => new FakeElement(tag),
    createTextNode: (text) => new FakeText(text),
  };
  globalThis.customElements = { define: (name, constructor) => registry.set(name, constructor) };
  return registry;
}

/** A ``hass`` stand-in whose websocket answers come from ``handlers[type](message)``. */
export function fakeHass(handlers, ids = ["sensor.foo", "sensor.taken"], language = undefined) {
  const sent = [];
  return {
    sent,
    language,
    entities: Object.fromEntries(ids.map((id) => [id, {}])),
    connection: {
      async sendMessagePromise(message) {
        sent.push(message);
        const handler = handlers[message.type.split("/")[1]];
        if (!handler) throw new Error(`unexpected command ${message.type}`);
        return handler(message);
      },
    },
  };
}
