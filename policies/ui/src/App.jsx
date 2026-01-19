import { useState } from 'react'
import { AppShell, Burger, Group, Title, ActionIcon, useMantineColorScheme } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { Moon, Sun, Github } from 'lucide-react'
import ChatInterface from './components/ChatInterface'
import ArtifactPreview from './components/ArtifactPreview'

export default function App() {
    const [opened, { toggle }] = useDisclosure()
    const [artifacts, setArtifacts] = useState(null)
    const { colorScheme, toggleColorScheme } = useMantineColorScheme()

    const handleArtifactsGenerated = (data, userMessage) => {
        setArtifacts({
            output: data.output,
            pr_url: data.pr_url
        })

        // If on mobile, we might want to auto-open the aside or show a notification
        // For now, we just set the state
    }

    return (
        <AppShell
            header={{ height: 60 }}
            navbar={{ width: 300, breakpoint: 'sm', collapsed: { mobile: !opened } }}
            aside={{
                width: 400,
                breakpoint: 'md',
                collapsed: { desktop: !artifacts, mobile: !artifacts }
            }}
            padding="md"
        >
            <AppShell.Header>
                <Group h="100%" px="md" justify="space-between">
                    <Group>
                        <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
                        <Title order={3}>MCP Bot</Title>
                    </Group>
                    <Group>
                        <ActionIcon variant="default" onClick={toggleColorScheme} size="lg">
                            {colorScheme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
                        </ActionIcon>
                        <ActionIcon variant="default" component="a" href="https://github.com" target="_blank" size="lg">
                            <Github size={18} />
                        </ActionIcon>
                    </Group>
                </Group>
            </AppShell.Header>

            <AppShell.Navbar p="md">
                {/* Future: History or Settings */}
                <Title order={5} mb="md">History</Title>
                <div className="text-sm text-gray-500">No history yet.</div>
            </AppShell.Navbar>

            <AppShell.Main>
                <ChatInterface onArtifactsGenerated={handleArtifactsGenerated} />
            </AppShell.Main>

            <AppShell.Aside p="md">
                {artifacts && (
                    <ArtifactPreview
                        artifacts={artifacts}
                        onClose={() => setArtifacts(null)}
                    />
                )}
            </AppShell.Aside>
        </AppShell>
    )
}
