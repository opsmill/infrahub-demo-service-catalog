# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Service Catalog demo built with Infrahub and Streamlit that allows users to request and manage network services through a web portal. The application demonstrates how to build a service factory on top of a source of truth system.

## Common Development Commands

### Docker Operations

- `invoke build` - Build Docker containers
- `invoke start` - Start the application with Docker Compose
- `invoke stop` - Stop Docker containers
- `invoke destroy` - Stop and remove volumes
- `invoke restart` - Restart containers

### Code Quality

- `invoke lint` - Run all linters (yamllint, ruff, mypy)
- `invoke format` - Format code with ruff
- `invoke lint-ruff` - Check code with ruff
- `invoke lint-mypy` - Type check with mypy
- `invoke lint-yaml` - Lint YAML files

### Testing

- `pytest` - Run all tests
- `pytest tests/unit/` - Run unit tests only
- `pytest tests/integration/` - Run integration tests
- `pytest -k test_name` - Run specific test

### Documentation

- `invoke docs` - Build documentation (requires npm in docs/ directory)
- `markdownlint docs/docs/**/*.mdx` - Lint documentation files for formatting issues
- Mermaid diagrams are supported in MDX files using standard ```mermaid code blocks

## Architecture Overview

### Core Components

1. **Streamlit Portal** (`service_catalog/`)
   - Entry point: `🏠_Home_Page.py` - Main portal interface
   - Service pages in `pages/` - Individual service request forms
   - `infrahub.py` - Infrahub SDK client wrapper with caching and dependency injection

2. **Infrahub Integration**
   - Uses Infrahub SDK for data management and service orchestration
   - GraphQL-based API communication
   - Branch-based change management support

3. **Service Implementation**
   - `generators/` - Infrahub generators for automated service provisioning
   - Example: `implement_dedicated_internet.py` allocates VLANs, IP prefixes, ports, and configures gateways

4. **Data Models**
   - `schemas/` - Infrahub schema definitions (DCIM, IPAM, services)
   - `protocols_*.py` - Type definitions for Infrahub objects
   - Initial data in `data/` - YAML fixtures for demo environment

### Key Patterns

- **Dependency Injection**: Uses `fast-depends` for managing Infrahub client instances
- **Resource Allocation**: Automated allocation from pools (VLANs, IP prefixes)
- **Service Lifecycle**: Services move through states (pending → active) with associated resource provisioning
- **Type Safety**: Comprehensive type hints with mypy validation

## Environment Configuration

Required environment variable:

- `INFRAHUB_ADDRESS` - URL of the Infrahub instance

## Development Tips

- The application uses Streamlit's session state for managing UI state
- Infrahub client is cached using `@st.cache_resource` decorator
- All Infrahub operations should use the dependency-injected client from `infrahub.py`
- Service generators run asynchronously in Infrahub after service creation

## Documentation Quality

### Linting and Formatting

When working on documentation files (`.mdx`), always run markdownlint to ensure consistent formatting:

```bash
# Check all documentation files
markdownlint docs/docs/**/*.mdx

# Fix auto-fixable issues
markdownlint docs/docs/**/*.mdx --fix
```

### Common Markdownlint Rules

- **MD032**: Lists must be surrounded by blank lines
- **MD022**: Headings must be surrounded by blank lines  
- **MD007**: Use consistent list indentation (4 spaces for nested items)
- **MD009**: No trailing spaces
- **MD031**: Fenced code blocks must be surrounded by blank lines
- **MD040**: Fenced code blocks should specify a language

### Documentation Standards

- Follow the Diataxis framework for content structure
- Use clear, actionable headings for guides
- Include code snippets with language specifications
- Add explanatory callouts (:::tip, :::info, :::warning) for important concepts
- Ensure all lists and code blocks have proper spacing

### Vale Style Guide

When working on documentation, run Vale to ensure consistent style:

```bash
# Run Vale on documentation files (as used in CI)
vale $(find ./docs -type f \( -name "*.mdx" -o -name "*.md" \) )

# Or just the getting-started docs to avoid node_modules noise
vale docs/docs/getting-started/*.mdx
```

#### Common Vale Issues to Fix

1. **Sentence Case for Headings**
   - Use sentence case for all headings (lowercase except first word and proper nouns)
   - Example: "Understanding the workflow" not "Understanding the Workflow"
   - Exception: Proper nouns like "Infrahub", "GitHub", "Streamlit"

2. **Spelling Exceptions**
   - Add technical terms to `.vale/styles/spelling-exceptions.txt`
   - Common additions: `IPs`, `Gbps`, `Mbps`, `UIs`, `configs`, `auditable`, `idempotently`
   - Keep terms alphabetically sorted in the file

3. **Word Choices**
   - Avoid "simple" and "easy" - use "straightforward" or "clear" instead
   - Use "for example:" instead of "e.g." or "i.e."
   - Keep "configs" as is (don't replace with "configurations")

4. **GitHub Capitalization**
   - Always capitalize as "GitHub" not "github"
   - Note: Vale's branded-terms rule may sometimes false positive on correct usage

### Documentation Writing Guidelines

**Applies to:** All MDX files (`**/*.mdx`)

**Role:** Expert Technical Writer and MDX Generator with:

- Deep understanding of Infrahub and its capabilities
- Expertise in network automation and infrastructure management
- Proficiency in writing structured MDX documents
- Awareness of developer ergonomics

**Documentation Purpose:**

- Guide users through installing, configuring, and using Infrahub in real-world workflows
- Explain concepts and system architecture clearly, including new paradigms introduced by Infrahub
- Support troubleshooting and advanced use cases with actionable, well-organized content
- Enable adoption by offering approachable examples and hands-on guides that lower the learning curve

**Structure:** Follows [Diataxis framework](https://diataxis.fr/)

- **Tutorials** (learning-oriented)
- **How-to guides** (task-oriented)
- **Explanation** (understanding-oriented)
- **Reference** (information-oriented)

**Tone and Style:**

- Professional but approachable: Avoid jargon unless well defined. Use plain language with technical precision
- Concise and direct: Prefer short, active sentences. Reduce fluff
- Informative over promotional: Focus on explaining how and why, not on marketing
- Consistent and structured: Follow a predictable pattern across sections and documents

**For Guides:**

- Use conditional imperatives: "If you want X, do Y. To achieve W, do Z."
- Focus on practical tasks and problems, not the tools themselves
- Address the user directly using imperative verbs: "Configure...", "Create...", "Deploy..."
- Maintain focus on the specific goal without digressing into explanations
- Use clear titles that state exactly what the guide shows how to accomplish

**For Topics:**

- Use a more discursive, reflective tone that invites understanding
- Include context, background, and rationale behind design decisions
- Make connections between concepts and to users' existing knowledge
- Present alternative perspectives and approaches where appropriate
- Use illustrative analogies and examples to deepen understanding

**Terminology and Naming:**

- Always define new terms when first used. Use callouts or glossary links if possible
- Prefer domain-relevant language that reflects the user's perspective (e.g., playbooks, branches, schemas, commits)
- Be consistent: follow naming conventions established by Infrahub's data model and UI

**Reference Files:**

- Documentation guidelines: `docs/docs/development/docs.mdx`
- Vale styles: `.vale/styles/`
- Markdown linting: `.markdownlint.yaml`

### Document Structure Patterns (Following Diataxis)

**How-to Guides Structure (Task-oriented, practical steps):**

```markdown
- Title and Metadata
    - Title should clearly state what problem is being solved (YAML frontmatter)
    - Begin with "How to..." to signal the guide's purpose
    - Optional: Imports for components (e.g., Tabs, TabItem, CodeBlock, VideoPlayer)
- Introduction
    - Brief statement of the specific problem or goal this guide addresses
    - Context or real-world use case that frames the guide
    - Clearly indicate what the user will achieve by following this guide
    - Optional: Links to related topics or more detailed documentation
- Prerequisites / Assumptions
    - What the user should have or know before starting
    - Environment setup or requirements
    - What prior knowledge is assumed
- Step-by-Step Instructions
    - Step 1: [Action/Goal]
        - Clear, actionable instructions focused on the task
        - Code snippets (YAML, GraphQL, shell commands, etc.)
        - Screenshots or images for visual guidance
        - Tabs for alternative methods (e.g., Web UI, GraphQL, Shell/cURL)
        - Notes, tips, or warnings as callouts
    - Step 2: [Action/Goal]
        - Repeat structure as above for each step
    - Step N: [Action/Goal]
        - Continue as needed
- Validation / Verification
    - How to check that the solution worked as expected
    - Example outputs or screenshots
    - Potential failure points and how to address them
- Advanced Usage / Variations
    - Optional: Alternative approaches for different circumstances
    - Optional: How to adapt the solution for related problems
    - Optional: Ways to extend or optimize the solution
- Related Resources
    - Links to related guides, reference materials, or explanation topics
    - Optional: Embedded videos or labs for further learning
```

**Topics Structure (Understanding-oriented, theoretical knowledge):**

```markdown
- Title and Metadata
    - Title should clearly indicate the topic being explained (YAML frontmatter)
    - Consider using "About..." or "Understanding..." in the title
    - Optional: Imports for components (e.g., Tabs, TabItem, CodeBlock, VideoPlayer)
- Introduction
    - Brief overview of what this explanation covers
    - Why this topic matters in the context of Infrahub
    - Questions this explanation will answer
- Main Content Sections
    - Concepts & Definitions
        - Clear explanations of key terms and concepts
        - How these concepts fit into the broader system
    - Background & Context
        - Historical context or evolution of the concept/feature
        - Design decisions and rationale behind implementations
        - Technical constraints or considerations
    - Architecture & Design (if applicable)
        - Diagrams, images, or explanations of structure
        - How components interact or relate to each other
    - Mental Models
        - Analogies and comparisons to help understanding
        - Different ways to think about the topic
    - Connection to Other Concepts
        - How this topic relates to other parts of Infrahub
        - Integration points and relationships
    - Alternative Approaches
        - Different perspectives or methodologies
        - Pros and cons of different approaches
- Further Reading
    - Links to related topics, guides, or reference materials
    - External resources for deeper understanding
```

### Quality and Clarity Checklist

**General Documentation:**

- Content is accurate and reflects the latest version of Infrahub
- Instructions are clear, with step-by-step guidance where needed
- Markdown formatting is correct and compliant with Infrahub's style
- Spelling and grammar are checked

**For Guides:**

- The guide addresses a specific, practical problem or task
- The title clearly indicates what will be accomplished
- Steps follow a logical sequence that maintains flow
- Each step focuses on actions, not explanations
- The guide omits unnecessary details that don't serve the goal
- Validation steps help users confirm their success
- The guide addresses real-world complexity rather than oversimplified scenarios

**For Topics:**

- The explanation is bounded to a specific topic area
- Content provides genuine understanding, not just facts
- Background and context are included to deepen understanding
- Connections are made to related concepts and the bigger picture
- Different perspectives or approaches are acknowledged where relevant
- The content remains focused on explanation without drifting into tutorial or reference material
- The explanation answers "why" questions, not just "what" or "how"