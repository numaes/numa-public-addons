# FSM Diagram Widget - Capabilities Audit

## Current Implementation Status

### ✅ Fully Implemented Features

#### 1. Core Diagram Functionality
- **Node Creation**: Double-click on canvas to create nodes (States, Transitions, Start, End)
- **Node Editing**: Double-click nodes to edit properties (label, code, events, outcomes)
- **Node Movement**: Drag nodes to reposition them
- **Multi-selection**: Shift+click or drag to select multiple nodes
- **Node Deletion**: Delete/Backspace keys to remove selected nodes

#### 2. Connection Management
- **Connection Creation**: Drag from output ports to input ports
- **Connection Visualization**: SVG paths with curves
- **Connection Selection**: Click to select connections
- **Connection Deletion**: Delete selected connections

#### 3. Visual Features
- **Zoom**: Mouse wheel zoom in/out (0.1x to 3x scale)
- **Pan**: Drag canvas background to pan
- **Zoom to Fit**: Button to fit all nodes in view
- **Node Highlighting**: Selected and hovered states
- **Active Node**: Highlight current execution node (via `activeNodeId` prop)

#### 4. Node Types Supported
- **Start Node**: Entry point for FSM (type: 'start')
- **State Node**: Waiting states with events (type: 'state')
- **Transition Node**: Execute code and determine outcomes (type: 'transition')
- **End Node**: Terminal state (type: 'end')

#### 5. State Editor Features
- **Label Editing**: Change state name
- **Event Management**: Add/remove events (output ports)
- **Event Naming**: Edit event names

#### 6. Transition Editor Features
- **Label Editing**: Change transition name
- **Code Editing**: Python code execution
- **Outcome Management**: Add/remove outcomes and map to destination states
- **Breakpoint Support**: Mark transitions as breakpoints (`is_breakpoint` flag)

#### 7. Data Persistence
- **Load from JSON**: Load diagram from `json_ui_schema` field
- **Save to JSON**: Save diagram state to `json_ui_schema` field
- **Automatic Save**: Changes saved automatically via `updateData()`
- **Undo Support**: History stack for undo operations (Ctrl+Z)

#### 8. Validation
- **Validation Button**: Trigger backend validation
- **Visual Feedback**: Verification badge when diagram is verified
- **Readonly Mode**: Enforced for production state definitions

#### 9. UI/UX Features
- **Help Modal**: Keyboard shortcuts and usage instructions
- **Loading States**: Spinner while data loads
- **Error Handling**: Fallback for empty/invalid data
- **Responsive Design**: Works with different viewport sizes

### ⚠️ Partially Implemented Features

#### 1. Global State Support
- **Backend Support**: ✅ Fully implemented (backend detects `is_global` flag)
- **Frontend Editor**: ❌ Missing - No UI to mark states as global
- **Visual Differentiation**: ❌ Missing - Global states look same as regular states
- **Validation**: ❌ Missing - No validation for single global state per FSM

### ❌ Missing Features / Enhancement Opportunities

#### 1. Advanced Node Properties
- **Node Colors/Styles**: No visual customization for node appearance
- **Node Icons**: Limited icon support (only breakpoint icon)
- **Node Notes**: No way to add documentation/notes to nodes

#### 2. Connection Features
- **Connection Labels**: No labels on connections showing event/outcome names
- **Connection Styles**: No visual differentiation for connection types
- **Connection Routing**: Simple straight lines, no intelligent routing

#### 3. Editing Improvements
- **Inline Editing**: No inline text editing (requires modal)
- **Bulk Operations**: No way to select and modify multiple nodes
- **Copy/Paste**: No copy-paste functionality for nodes
- **Node Templates**: No template library for common patterns

#### 4. Visualization Enhancements
- **Minimap**: No overview/minimap for large diagrams
- **Grid/Snap**: No grid or snap-to-grid functionality
- **Alignment Tools**: No align/distribute tools for nodes
- **Zoom Controls**: Limited to mouse wheel (no buttons/slider)

#### 5. Validation & Feedback
- **Real-time Validation**: No client-side validation while editing
- **Error Markers**: No visual indicators for invalid configurations
- **Warning System**: No warnings for potential issues (e.g., unreachable states)

#### 6. Accessibility
- **Keyboard Navigation**: Limited keyboard support (only Delete/Undo)
- **Screen Reader Support**: Limited ARIA labels and descriptions
- **High Contrast Mode**: No special styling for accessibility

#### 7. Collaboration Features
- **Comments/Annotations**: No way to add comments to diagram
- **Version History**: No visual diff or history view
- **Locking**: No concurrent edit protection

#### 8. Performance
- **Large Diagram Handling**: May struggle with 100+ nodes
- **Virtual Scrolling**: Not implemented for node rendering
- **Optimization**: No lazy loading or rendering optimization

## Code Structure Analysis

### Component Hierarchy
```
FSMDiagram (Main Component)
├── FSMNode (Node Rendering)
├── FSMStateEditor (State Property Editor)
├── FSMTransitionEditor (Transition Property Editor)
└── FSMNodeCreator (Node Creation Menu)
```

### Key Files
- **fsm_diagram.js**: Main component logic (651 lines)
- **fsm_diagram.xml**: Main template (127 lines)
- **fsm_node.js**: Node component (66 lines)
- **fsm_node.xml**: Node template (46 lines)
- **fsm_state_editor.js**: State editor (37 lines)
- **fsm_transition_editor.js**: Transition editor
- **fsm_node_creator.js**: Node creator

### State Management
- Uses OWL `useState` for reactive state
- Diagram state: `{ nodes, connections, transform, editingNode, ... }`
- History stack for undo/redo

### Data Flow
1. **Load**: `loadData()` → Parse JSON → Set state
2. **Edit**: User interaction → Update state → `updateData()` → Save to backend
3. **Compile**: Backend `compile_ui_schema_to_definition()` processes `json_ui_schema`

## Implementation Gaps for Global States

### Required Changes

1. **FSMStateEditor** (`fsm_state_editor.js` + `fsm_state_editor.xml`)
   - Add checkbox for "Global State" option
   - Store `is_global` in state
   - Pass `is_global` to `onSave` callback

2. **FSMNode** (`fsm_node.xml` + `fsm_node.scss`)
   - Add CSS class `o_fsm_node_global` for global states
   - Visual differentiation (e.g., different border, icon)

3. **FSMDiagram** (`fsm_diagram.js`)
   - Load `is_global` from node data in `loadData()`
   - Save `is_global` in `updateData()`
   - Validate only one global state per FSM
   - Show warning when multiple global states exist

4. **Validation** (`fsm_diagram.js`)
   - Check for multiple global states before validation
   - Show notification if validation fails due to multiple global states

## Recommendations

### High Priority (For Global State Feature)
1. ✅ **Implement Global State UI** - Add checkbox in state editor
2. ✅ **Visual Differentiation** - Add styling for global states
3. ✅ **Validation** - Ensure only one global state per FSM

### Medium Priority (Quality of Life)
1. **Connection Labels** - Show event/outcome names on connections
2. **Inline Editing** - Allow double-click to edit text directly
3. **Better Error Feedback** - Visual indicators for validation errors

### Low Priority (Nice to Have)
1. **Minimap** - Overview for large diagrams
2. **Copy/Paste** - Duplicate nodes/patterns
3. **Templates** - Pre-built common patterns

## Testing Checklist

### Global State Feature Tests
- [ ] Can mark a state as global via UI
- [ ] Global state saves correctly to JSON
- [ ] Global state loads correctly from JSON
- [ ] Visual differentiation visible for global states
- [ ] Validation prevents multiple global states
- [ ] Warning shown when multiple global states exist
- [ ] Backend compilation includes `global_state_id` correctly

### Regression Tests
- [ ] Existing diagrams load correctly after changes
- [ ] Non-global states still work as before
- [ ] All existing features continue to work
- [ ] Undo/redo works with global state changes
