# Pensare Templates

Templates define the initial structure for new Pensare projects. The setup wizard scans `${CLAUDE_PLUGIN_ROOT}/templates/` for `.json` files and presents them as options during `pensare setup`.

## JSON Schema

Each template file must contain a single JSON object with these fields:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Machine-readable identifier (e.g., `workspace`) |
| `display_name` | string | Human-readable name shown in the setup wizard |
| `description` | string | One-line summary of the template's purpose |
| `setup_questions` | string[] | Questions asked during `pensare setup` to customize the project |
| `structure` | object | Defines files and directories to create (see below) |

### `structure` Object

| Field | Type | Description |
|-------|------|-------------|
| `context_files` | array | Files to create in the project root. Each has `name`, `sections` (list of heading names), and `description`. |
| `directories` | array | Subdirectories to create. Each has `name`, `description`, `index_file` (filename for the index), and `index_template` (initial content). |
| `overview_template` | string | Markdown template for the main `Overview.md` file. Uses variable substitution. |

## Template Variables

Variables use `{variable_name}` syntax and are substituted during project creation:

| Variable | Source |
|----------|--------|
| `{project_name}` | Name provided during `pensare setup` |
| `{project_description}` | Description provided during `pensare setup` |
| `{folder_table}` | Auto-generated markdown table rows from `directories` entries |
| `{custom_var}` | Any custom variable defined in your template's `setup_questions` flow |

## Creating Custom Templates

1. Create a `.json` file in this directory following the schema above.
2. The file will automatically appear in the setup wizard on the next `pensare setup`.
3. At minimum, provide `name`, `display_name`, `description`, and `structure` with an `overview_template`.
4. `setup_questions` and `directories` are optional -- a template can be as simple as a single overview file.

## Included Templates

- **workspace.json** -- Long-lived project for investigations, debugging runs, and issue tracking.
