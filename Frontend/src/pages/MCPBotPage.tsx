import React, { useState, useRef, useEffect } from 'react';
import { Bot, User, Send, Copy, Check, ExternalLink, AlertCircle } from 'lucide-react';

interface Message {
    role: 'user' | 'bot';
    content: string;
    pr_url?: string;
    status?: 'success' | 'failure';
    timestamp?: string;
    isError?: boolean;
}

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:3001';

export const MCPBotPage: React.FC = () => {
    const [messages, setMessages] = useState<Message[]>([
        {
            role: 'bot',
            content: '👋 Hello! I can help you create and manage Gatekeeper policies.\n\n**Try these examples:**\n- `require labels team and org for deployments`\n- `banish pod run root`\n- `update require-resource exempt namespace nginx`\n\nJust type your request in natural language!'
        }
    ]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const viewportRef = useRef<HTMLDivElement>(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!input.trim() || isLoading) return;

        const userMessage = input.trim();
        setInput('');
        setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
        setIsLoading(true);

        try {
            const response = await fetch(`${API_BASE_URL}/api/mcp/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: userMessage })
            });

            const data = await response.json();
            console.log("Backend response:", data);

            if (!data) {
                throw new Error("Received empty response from backend");
            }

            // Handle new response format: error, status, pr_url, policy info
            let botContent = "";
            const isError = !!data.error || data.status === "failure";

            if (data.error) {
                botContent = `❌ **Error:** ${data.error}`;
            } else if (data.status === "success") {
                // Build success message with policy details
                let successParts = ["✅ **Success!**"];

                if (data.policy) {
                    const policy = data.policy;
                    successParts.push(`\n\n**Policy Details:**`);
                    if (policy.policy_name) {
                        successParts.push(`- **Policy:** \`${policy.policy_name}\``);
                    }
                    if (policy.intent) {
                        successParts.push(`- **Intent:** ${policy.intent}`);
                    }
                    if (policy.target_kinds && policy.target_kinds.length > 0) {
                        successParts.push(`- **Target Kinds:** ${policy.target_kinds.join(', ')}`);
                    }
                    if (policy.excluded_namespaces && policy.excluded_namespaces.length > 0) {
                        successParts.push(`- **Excluded Namespaces:** ${policy.excluded_namespaces.join(', ')}`);
                    }
                }

                if (data.pr_url) {
                    successParts.push(`\n\n🔗 **PR Created:** [View PR](${data.pr_url})`);
                }

                botContent = successParts.join('\n');
            } else if (data.status === "failure") {
                botContent = "❌ **Failed** - An error occurred.";
            } else {
                botContent = `Status: ${data.status || "unknown"}`;
            }

            const botMessage: Message = {
                role: 'bot',
                content: botContent,
                pr_url: data.pr_url,
                status: data.status,
                timestamp: new Date().toISOString(),
                isError: isError
            };

            setMessages(prev => [...prev, botMessage]);

            // Handle error response from exception handler
            if (data.detail) {
                setMessages(prev => [...prev, {
                    role: 'bot',
                    content: `❌ **Error:** ${data.detail}`,
                    isError: true
                }]);
            }
        } catch (error: any) {
            console.error("Chat error:", error);
            setMessages(prev => [...prev, {
                role: 'bot',
                content: `Error: ${error.message}`,
                isError: true
            }]);
        } finally {
            setIsLoading(false);
        }
    };

    const copyToClipboard = (text: string, index: number) => {
        navigator.clipboard.writeText(text);
        setCopiedIndex(index);
        setTimeout(() => setCopiedIndex(null), 2000);
    };

    const formatMessage = (content: string) => {
        // Simple markdown-like formatting
        let formatted = content
            .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:text-blue-800 underline">$1</a>')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/`(.*?)`/g, '<code class="bg-gray-100 px-1 py-0.5 rounded text-sm font-mono">$1</code>')
            .replace(/\n/g, '<br />');

        return { __html: formatted };
    };

    return (
        <div className="flex h-[calc(100vh-4rem)] bg-gray-50">
            {/* Main Chat Area */}
            <div className="flex-1 flex flex-col transition-all duration-200 min-w-0">
                <div className="bg-white border-b border-gray-200 px-6 py-4">
                    <h1 className="text-2xl font-bold text-gray-900">Kubecheck Bot</h1>
                    <p className="text-sm text-gray-600 mt-1">AI-powered Gatekeeper policy assistant</p>
                </div>

                {/* Messages */}
                <div ref={viewportRef} className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                    {messages.map((msg, idx) => (
                        <div
                            key={idx}
                            className={`flex items-start gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                        >
                            {msg.role === 'bot' && (
                                <div className="flex-shrink-0 w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center">
                                    <Bot className="h-5 w-5 text-white" />
                                </div>
                            )}
                            <div
                                className={`relative max-w-[80%] rounded-lg shadow-md p-4 ${msg.role === 'user'
                                    ? 'bg-indigo-600 text-white'
                                    : msg.isError
                                        ? 'bg-red-50 border border-red-200 text-red-900'
                                        : 'bg-white border border-gray-200 text-gray-900'
                                    }`}
                            >
                                <div className="flex items-start justify-between gap-2 mb-2">
                                    <div className="flex items-center gap-2 flex-wrap">
                                        {msg.pr_url && (
                                            <a
                                                href={msg.pr_url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="inline-flex items-center gap-1 px-2 py-1 bg-green-100 text-green-800 rounded text-xs font-medium hover:bg-green-200"
                                            >
                                                <ExternalLink className="h-3 w-3" />
                                                PR Created
                                            </a>
                                        )}
                                        {msg.status === 'failure' && (
                                            <span className="inline-flex items-center gap-1 px-2 py-1 bg-red-100 text-red-800 rounded text-xs font-medium">
                                                <AlertCircle className="h-3 w-3" />
                                                Failed
                                            </span>
                                        )}
                                        {msg.status === 'success' && !msg.pr_url && (
                                            <span className="inline-flex items-center gap-1 px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs font-medium">
                                                Success
                                            </span>
                                        )}
                                    </div>
                                    <button
                                        onClick={() => copyToClipboard(msg.content, idx)}
                                        className="text-gray-400 hover:text-gray-600 transition-colors"
                                        title="Copy message"
                                    >
                                        {copiedIndex === idx ? (
                                            <Check className="h-4 w-4 text-green-600" />
                                        ) : (
                                            <Copy className="h-4 w-4" />
                                        )}
                                    </button>
                                </div>
                                <div
                                    className="prose prose-sm max-w-none"
                                    dangerouslySetInnerHTML={formatMessage(msg.content)}
                                />
                            </div>
                            {msg.role === 'user' && (
                                <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gray-400 flex items-center justify-center">
                                    <User className="h-5 w-5 text-white" />
                                </div>
                            )}
                        </div>
                    ))}
                    {isLoading && (
                        <div className="flex items-start gap-3">
                            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center">
                                <Bot className="h-5 w-5 text-white" />
                            </div>
                            <div className="bg-white border border-gray-200 rounded-lg shadow-md p-4">
                                <div className="flex items-center gap-2 text-gray-600">
                                    <div className="animate-spin rounded-full h-4 w-4 border-2 border-indigo-600 border-t-transparent"></div>
                                    <span className="text-sm">Thinking...</span>
                                </div>
                            </div>
                        </div>
                    )}
                    <div ref={messagesEndRef} />
                </div>

                {/* Input Form */}
                <div className="bg-white border-t border-gray-200 px-6 py-4">
                    <form onSubmit={handleSubmit} className="flex gap-2">
                        <input
                            type="text"
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            placeholder="Type a message..."
                            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                            disabled={isLoading}
                        />
                        <button
                            type="submit"
                            disabled={isLoading || !input.trim()}
                            className="px-6 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
                        >
                            <Send className="h-5 w-5" />
                            Send
                        </button>
                    </form>
                </div>
            </div>

        </div>
    );
};

