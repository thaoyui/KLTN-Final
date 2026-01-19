import { useState, useRef, useEffect } from 'react'
import { Paper, TextInput, ActionIcon, ScrollArea, Stack, Text, Avatar, Group, Loader, Box, useMantineColorScheme, Badge, Button, Tooltip } from '@mantine/core'
import { Send, Bot, User, Copy, Check, ExternalLink, AlertCircle } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'

export default function ChatInterface({ onArtifactsGenerated }) {
    const { colorScheme } = useMantineColorScheme()
    const isDark = colorScheme === 'dark'

    const [messages, setMessages] = useState([
        { 
            role: 'bot', 
            content: '👋 Hello! I can help you create and manage Gatekeeper policies.\n\n**Try these examples:**\n- `require labels team and org for deployments`\n- `banish pod run root`\n- `update require-resource exempt namespace nginx`\n\nJust type your request in natural language!' 
        }
    ])
    const [input, setInput] = useState('')
    const [isLoading, setIsLoading] = useState(false)
    const [lastResponse, setLastResponse] = useState(null)
    const [copiedIndex, setCopiedIndex] = useState(null)
    const viewport = useRef(null)

    const scrollToBottom = () => {
        viewport.current?.scrollTo({ top: viewport.current.scrollHeight, behavior: 'smooth' })
    }

    useEffect(() => {
        scrollToBottom()
    }, [messages])

    const handleSubmit = async (e) => {
        e.preventDefault()
        if (!input.trim() || isLoading) return

        const userMessage = input.trim()
        setInput('')
        setMessages(prev => [...prev, { role: 'user', content: userMessage }])
        setIsLoading(true)
        setLastResponse(null)

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: userMessage })
            })

            const data = await response.json()
            console.log("Backend response:", data)
            setLastResponse(data)

            if (!data) {
                throw new Error("Received empty response from backend")
            }

            // Handle new response format: error, status, pr_url
            let botContent = ""
            const isError = !!data.error || data.status === "failure"
            
            if (data.error) {
                botContent = `❌ **Error:** ${data.error}`
            } else if (data.status === "success") {
                if (data.pr_url) {
                    botContent = `✅ **Success!** PR created: [View PR](${data.pr_url})`
                } else {
                    botContent = "✅ **Success!** (No PR URL provided)"
                }
            } else if (data.status === "failure") {
                botContent = "❌ **Failed** - An error occurred."
            } else {
                botContent = `Status: ${data.status || "unknown"}`
            }

            const botMessage = {
                role: 'bot',
                content: botContent,
                pr_url: data.pr_url,
                status: data.status,
                timestamp: new Date().toISOString(),
                isError: isError
            }
            
            setMessages(prev => [...prev, botMessage])
            
            if (data.pr_url) {
                onArtifactsGenerated({ output: botContent, pr_url: data.pr_url }, userMessage)
            }
            
            // Handle error response from exception handler
            if (data.detail) {
                setMessages(prev => [...prev, { 
                    role: 'bot', 
                    content: `❌ **Error:** ${data.detail}`,
                    isError: true
                }])
            }
        } catch (error) {
            console.error("Chat error:", error)
            setMessages(prev => [...prev, { role: 'bot', content: `Error: ${error.message}` }])
            setLastResponse({ error: error.message })
        } finally {
            setIsLoading(false)
        }
    }

    return (
        <Stack h="100%" gap="md">
            <ScrollArea h="100%" viewportRef={viewport} type="always">
                <Stack gap="md" pb="xl">
                    {messages.map((msg, idx) => (
                        <Group key={idx} align="flex-start" justify={msg.role === 'user' ? 'flex-end' : 'flex-start'} gap="xs">
                            {msg.role === 'bot' && (
                                <Avatar color="brand" radius="xl"><Bot size={20} /></Avatar>
                            )}
                            <Paper
                                p="md"
                                radius="md"
                                bg={msg.role === 'user' ? (isDark ? 'brand.8' : 'brand.6') : (isDark ? 'slate.8' : 'gray.1')}
                                c={msg.role === 'user' ? 'white' : (isDark ? 'slate.1' : 'slate.9')}
                                maw="80%"
                                shadow="md"
                                style={{ position: 'relative' }}
                            >
                                <Group justify="space-between" mb="xs">
                                    {msg.pr_url && (
                                        <Badge color="green" leftSection={<ExternalLink size={12} />}>
                                            <a href={msg.pr_url} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                                                PR Created
                                            </a>
                                        </Badge>
                                    )}
                                    {msg.status === 'failure' && (
                                        <Badge color="red" leftSection={<AlertCircle size={12} />}>
                                            Failed
                                        </Badge>
                                    )}
                                    {msg.status === 'success' && !msg.pr_url && (
                                        <Badge color="blue">Success</Badge>
                                    )}
                                </Group>
                                <Box style={{ overflowWrap: 'break-word' }}>
                                    <ReactMarkdown
                                        components={{
                                            code: ({ node, inline, className, children, ...props }) => {
                                                const match = /language-(\w+)/.exec(className || '')
                                                return !inline && match ? (
                                                    <SyntaxHighlighter
                                                        language={match[1]}
                                                        style={vscDarkPlus}
                                                        PreTag="div"
                                                        {...props}
                                                    >
                                                        {String(children).replace(/\n$/, '')}
                                                    </SyntaxHighlighter>
                                                ) : (
                                                    <code className={className} {...props}>
                                                        {children}
                                                    </code>
                                                )
                                            }
                                        }}
                                    >
                                        {msg.content}
                                    </ReactMarkdown>
                                </Box>
                                <Tooltip label="Copy message">
                                    <ActionIcon
                                        variant="subtle"
                                        size="sm"
                                        style={{ position: 'absolute', top: 8, right: 8 }}
                                        onClick={() => {
                                            navigator.clipboard.writeText(msg.content)
                                            setCopiedIndex(idx)
                                            setTimeout(() => setCopiedIndex(null), 2000)
                                        }}
                                    >
                                        {copiedIndex === idx ? <Check size={14} /> : <Copy size={14} />}
                                    </ActionIcon>
                                </Tooltip>
                            </Paper>
                            {msg.role === 'user' && (
                                <Avatar color="gray" radius="xl"><User size={20} /></Avatar>
                            )}
                        </Group>
                    ))}
                    {isLoading && (
                        <Group align="center" gap="xs">
                            <Avatar color="brand" radius="xl"><Bot size={20} /></Avatar>
                            <Paper p="xs" radius="md" bg="slate.8">
                                <Group gap="xs">
                                    <Loader size="xs" type="dots" />
                                    <Text size="sm" c="dimmed">Thinking...</Text>
                                </Group>
                            </Paper>
                        </Group>
                    )}
                </Stack>
            </ScrollArea>

            <div className="p-4 border-t">
                <form onSubmit={handleSubmit}>
                    <Group>
                        <TextInput
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            placeholder="Type a message..."
                            style={{ flex: 1 }}
                            disabled={isLoading}
                        />
                        <ActionIcon type="submit" loading={isLoading} size="lg" variant="filled">
                            <Send size={18} />
                        </ActionIcon>
                    </Group>
                </form>
            </div>
        </Stack>
    )
}
