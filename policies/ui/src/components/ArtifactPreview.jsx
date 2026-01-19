import { Box, Paper, Group, Title, ActionIcon, Stack, Alert, ScrollArea, Text } from '@mantine/core'
import { X, Check, AlertTriangle, Terminal } from 'lucide-react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'

export default function ArtifactPreview({ artifacts, onClose }) {
    const prUrl = artifacts.pr_url
    const output = artifacts.output

    return (
        <Stack h="100%" gap={0}>
            <Paper p="md" radius={0} withBorder style={{ borderLeft: 0, borderRight: 0, borderTop: 0 }}>
                <Group justify="space-between">
                    <Title order={4}>CLI Output</Title>
                    <ActionIcon variant="subtle" color="gray" onClick={onClose}>
                        <X size={20} />
                    </ActionIcon>
                </Group>
            </Paper>

            <Box flex={1} style={{ position: 'relative', overflow: 'hidden' }}>
                <ScrollArea h="100%" type="auto">
                    <SyntaxHighlighter
                        language="bash"
                        style={vscDarkPlus}
                        customStyle={{ margin: 0, padding: '1rem', fontSize: '13px', minHeight: '100%' }}
                        showLineNumbers={false}
                        wrapLines={true}
                    >
                        {output || "No output received."}
                    </SyntaxHighlighter>
                </ScrollArea>
            </Box>

            <Paper p="md" withBorder radius={0} style={{ borderLeft: 0, borderRight: 0, borderBottom: 0 }}>
                {prUrl ? (
                    <Alert variant="light" color="green" title="Success" icon={<Check size={16} />}>
                        <Stack gap="xs">
                            <Text size="sm">Pull Request Created!</Text>
                            <Text component="a" href={prUrl} target="_blank" size="sm" c="blue" style={{ wordBreak: 'break-all' }}>
                                {prUrl}
                            </Text>
                        </Stack>
                    </Alert>
                ) : (
                    <Alert variant="light" color="blue" title="Status" icon={<Terminal size={16} />}>
                        <Text size="sm">
                            Check the CLI output above for details.
                        </Text>
                    </Alert>
                )}
            </Paper>
        </Stack>
    )
}
