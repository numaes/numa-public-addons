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
