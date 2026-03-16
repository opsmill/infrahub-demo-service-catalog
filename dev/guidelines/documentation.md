# Documentation Guidelines

## Linting and Formatting

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

## Documentation Standards

- Follow the Diataxis framework for content structure
- Use clear, actionable headings for guides
- Include code snippets with language specifications
- Add explanatory callouts (:::tip, :::info, :::warning) for important concepts
- Ensure all lists and code blocks have proper spacing

## Vale Style Guide

Run Vale to ensure consistent style:

```bash
# Run Vale on documentation files (as used in CI)
vale $(find ./docs -type f \( -name "*.mdx" -o -name "*.md" \) )

# Or just the getting-started docs to avoid node_modules noise
vale docs/docs/getting-started/*.mdx
```

### Common Vale Issues to Fix

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

## Writing Guidelines

**Applies to:** All MDX files (`**/*.mdx`)

### Tone and Style

- Professional but approachable: Avoid jargon unless well defined. Use plain language with technical precision
- Concise and direct: Prefer short, active sentences. Reduce fluff
- Informative over promotional: Focus on explaining how and why, not on marketing
- Consistent and structured: Follow a predictable pattern across sections and documents

### For Guides

- Use conditional imperatives: "If you want X, do Y. To achieve W, do Z."
- Focus on practical tasks and problems, not the tools themselves
- Address the user directly using imperative verbs: "Configure...", "Create...", "Deploy..."
- Maintain focus on the specific goal without digressing into explanations
- Use clear titles that state exactly what the guide shows how to accomplish

### For Topics

- Use a more discursive, reflective tone that invites understanding
- Include context, background, and rationale behind design decisions
- Make connections between concepts and to users' existing knowledge
- Present alternative perspectives and approaches where appropriate
- Use illustrative analogies and examples to deepen understanding

### Terminology and Naming

- Always define new terms when first used. Use callouts or glossary links if possible
- Prefer domain-relevant language that reflects the user's perspective (e.g., playbooks, branches, schemas, commits)
- Be consistent: follow naming conventions established by Infrahub's data model and UI

### Reference Files

- Documentation guidelines: `docs/docs/development/docs.mdx`
- Vale styles: `.vale/styles/`
- Markdown linting: `.markdownlint.yaml`

## Document Structure Patterns (Following Diataxis)

### How-to Guides Structure (Task-oriented, practical steps)

- Title and Metadata
    - Title should clearly state what problem is being solved (YAML frontmatter)
    - Begin with "How to..." to signal the guide's purpose
- Introduction
    - Brief statement of the specific problem or goal this guide addresses
    - Context or real-world use case that frames the guide
- Prerequisites / Assumptions
    - What the user should have or know before starting
- Step-by-Step Instructions
    - Clear, actionable instructions focused on the task
    - Code snippets (YAML, GraphQL, shell commands, etc.)
    - Notes, tips, or warnings as callouts
- Validation / Verification
    - How to check that the solution worked as expected
- Related Resources
    - Links to related guides, reference materials, or explanation topics

### Topics Structure (Understanding-oriented, theoretical knowledge)

- Title and Metadata
    - Title should clearly indicate the topic being explained
    - Consider using "About..." or "Understanding..." in the title
- Introduction
    - Brief overview of what this explanation covers
    - Why this topic matters in the context of Infrahub
- Main Content Sections
    - Concepts and Definitions
    - Background and Context
    - Architecture and Design (if applicable)
    - Connection to Other Concepts
- Further Reading
    - Links to related topics, guides, or reference materials

## Quality and Clarity Checklist

### General Documentation

- Content is accurate and reflects the latest version of Infrahub
- Instructions are clear, with step-by-step guidance where needed
- Markdown formatting is correct and compliant with Infrahub's style
- Spelling and grammar are checked

### For Guides

- The guide addresses a specific, practical problem or task
- The title clearly indicates what will be accomplished
- Steps follow a logical sequence that maintains flow
- Each step focuses on actions, not explanations
- Validation steps help users confirm their success

### For Topics

- The explanation is bounded to a specific topic area
- Content provides genuine understanding, not just facts
- Background and context are included to deepen understanding
- Connections are made to related concepts and the bigger picture
- The explanation answers "why" questions, not just "what" or "how"
