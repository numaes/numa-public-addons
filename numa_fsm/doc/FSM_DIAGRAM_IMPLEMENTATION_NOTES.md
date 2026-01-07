# FSM Diagram Implementation Notes

This document outlines the key architectural patterns used in the FSM Diagram component, based on a successful implementation that resolves previous event handling issues. The goal is to provide a clear reference for future development and to avoid repeating past mistakes.

## Core Architectural Pattern: Manual Event Management

The FSM Diagram component uses a manual event management strategy to handle all click, double-click, and drag-and-drop interactions. This approach was chosen over the standard `useDraggable` hook to provide the necessary level of control and to avoid event conflicts in a complex UI.

### Key Principles:

1.  **Single Entry Point:** All mouse interactions begin with a single `t-on-pointerdown` event handler on the main container element. This handler is responsible for determining the user's intent (pan, drag node, start connection, click, or double-click).

2.  **Manual State Tracking:** A `dragState` object is used to manually track the current state of the interaction (e.g., `{ type: 'pan', ... }`, `{ type: 'node', ... }`). This object is created in the `onMouseDown` handler and cleared in the `onGlobalMouseUp` handler.

3.  **Global Listeners for Drag Operations:** The `pointermove` and `pointerup` events are handled by global listeners attached to the `document`. This is a robust pattern that ensures drag operations are correctly tracked even if the user's mouse leaves the component's boundaries. These listeners are added in the `setup` method and cleaned up in `onWillUnmount`.

4.  **Manual Double-Click Detection:** The `onMouseDown` handler includes logic to detect a double-click by measuring the time (e.g., < 300ms) and distance (e.g., < 5px) between two consecutive clicks. If a double-click is detected, the appropriate action is triggered, and the drag operation is prevented from starting.

5.  **Pointer Capture:** The `setPointerCapture` and `releasePointerCapture` methods are used on the event target. This is a crucial detail for creating a robust drag-and-drop experience, as it ensures that all subsequent mouse events are dispatched to the element that initiated the drag, even if the pointer moves outside its bounds.

### Summary of Learnings:

The primary lesson from the previous failed attempts is that in a complex component like this, mixing different event handling strategies (e.g., a `useDraggable` hook with separate `t-on-dblclick` handlers) can lead to unpredictable event conflicts.

The successful pattern is to take full control of the event stream from the initial `pointerdown` event and manage all subsequent logic (clicks, double-clicks, drags) manually. This provides a clear, consistent, and robust solution that is well-suited for the complexities of the Odoo framework.

## Data Persistence and Component Lifecycle in Odoo 18

Managing the lifecycle of an Owl component within the Odoo 18 framework requires careful handling of asynchronous data loading and property updates.

### 1. The Reactive Synchronization Pattern

In Odoo 18, widget properties (like `this.props.value`) are often `undefined` during the initial setup while the ORM completes the `web_read` operation. 

**Lesson Learned:** Do not rely solely on `onWillStart` or `setup` for data initialization. Use `useEffect` to reactively synchronize the component's internal state whenever properties change.

```javascript
useEffect(
    (val, resId) => {
        // Fallback to record data if props.value is not yet updated
        const dataToLoad = (val !== undefined) ? val : this.props.record.data[this.props.name];
        
        if (dataToLoad !== undefined) {
            this.loadData(dataToLoad);
        }
    },
    () => [this.props.value, this.props.record.resId]
);
```

### 2. Handling Asynchronous Loading Gaps

There is often a lag between the component's mounting and the availability of data.

**Key Principles:**
- **Deterministic Loading:** Ensure the component always reaches a "loaded" state. Use a safety timeout if necessary to force a default state if Odoo fails to provide data within a reasonable timeframe (e.g., 4 seconds).
- **Deep Cloning:** Use `JSON.parse(JSON.stringify(data))` when assigning received objects to the component's `useState`. This breaks references to Odoo's internal Proxies, preventing unexpected side effects and ensuring deep reactivity.
- **Persistent Viewport:** Keep the root containers of the diagram (Viewport, SVG, Nodes Layer) static in the XML. Only conditionally render their *content*. This provides stable nodes for Odoo's internal observers and avoids the "parameter 1 is not of type Node" error during asynchronous re-renders.

### 3. Separation of Navigation and Edition

**Optimization:** Panning and zooming operations should be purely visual and should **not** trigger `updateData()` or mark the record as "dirty" (`isDirty`). Only structural changes (moving nodes, creating/deleting elements) should invoke the persistence layer.

### 4. Immutable State Updates

When updating nodes or connections during drag operations, always use immutable patterns (e.g., `this.state.nodes = this.state.nodes.map(...)`). This ensures that Owl detects the change and updates the dependent SVG paths in real-time without needing manual DOM manipulation.
