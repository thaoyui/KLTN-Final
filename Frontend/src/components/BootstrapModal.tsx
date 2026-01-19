import React, { useEffect, useMemo, useState } from 'react';
import { RefreshCw, AlertTriangle, X } from 'lucide-react';

export type BootstrapNodeStatus = 'ready' | 'not_bootstrapped' | 'venv_missing' | 'unreachable';

export interface BootstrapNode {
    name: string;
    role?: 'master' | 'worker' | string;
    status: BootstrapNodeStatus;
    note?: string;
}

interface BootstrapModalProps {
    isOpen: boolean;
    onClose: () => void;
    nodes: BootstrapNode[];
    onBootstrap: (selectedNodes: BootstrapNode[]) => void;
    isLoading?: boolean;
}

export const BootstrapModal: React.FC<BootstrapModalProps> = ({
    isOpen,
    onClose,
    nodes,
    onBootstrap,
    isLoading = false,
}) => {
    const [selected, setSelected] = useState<Record<string, boolean>>({});

    useEffect(() => {
        if (isOpen) {
            setSelected({});
        }
    }, [isOpen, nodes]);

    const selectableNodes = useMemo(
        () => nodes.filter(n => n.status !== 'ready' && n.status !== 'unreachable'),
        [nodes]
    );

    const toggleNode = (name: string) => {
        setSelected(prev => ({ ...prev, [name]: !prev[name] }));
    };

    const handleSubmit = () => {
        const chosen = selectableNodes.filter(n => selected[n.name]);
        if (chosen.length === 0) return;
        onBootstrap(chosen);
    };

    if (!isOpen) return null;

    const statusBadge = (status: BootstrapNodeStatus) => {
        switch (status) {
            case 'ready':
                return (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        Ready
                    </span>
                );
            case 'not_bootstrapped':
                return (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
                        Not bootstrapped
                    </span>
                );
            case 'unreachable':
                return (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                        Unreachable
                    </span>
                );
            case 'venv_missing':
            default:
                return (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
                        Venv missing
                    </span>
                );
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black bg-opacity-50">
            <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[90vh] flex flex-col">
                {/* Header */}
                <div className="p-6 border-b border-gray-200 flex items-center justify-between">
                    <div>
                        <h2 className="text-xl font-semibold text-gray-900">Bootstrap Nodes</h2>
                        <p className="text-sm text-gray-600">
                            Chọn các node chưa bootstrap để chạy playbook.
                        </p>
                    </div>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-500">
                        <X className="h-6 w-6" />
                    </button>
                </div>

                {/* Content */}
                <div className="p-6 overflow-y-auto flex-1 space-y-4">
                    {nodes.length === 0 ? (
                        <div className="text-center text-gray-500 text-sm py-10">
                            Không có node nào để hiển thị.
                        </div>
                    ) : (
                        <div className="space-y-3">
                            {nodes.map(node => {
                                const disabled = node.status === 'ready' || node.status === 'unreachable';
                                const isChecked = !!selected[node.name];
                                return (
                                    <label
                                        key={node.name}
                                        className={`flex items-start space-x-3 p-3 border rounded-lg hover:bg-gray-50 ${disabled ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer'
                                            }`}
                                    >
                                        <input
                                            type="checkbox"
                                            className="mt-1 h-4 w-4 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500"
                                            disabled={disabled}
                                            checked={isChecked}
                                            onChange={() => toggleNode(node.name)}
                                        />
                                        <div className="flex-1">
                                            <div className="flex items-center space-x-2">
                                                <span className="font-medium text-gray-900">{node.name}</span>
                                                {node.role && (
                                                    <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-800 capitalize">
                                                        {node.role}
                                                    </span>
                                                )}
                                                {statusBadge(node.status)}
                                            </div>
                                            {node.note && <p className="text-xs text-gray-600 mt-1">{node.note}</p>}
                                        </div>
                                    </label>
                                );
                            })}
                        </div>
                    )}

                    <div className="bg-blue-50 border border-blue-100 rounded-md p-3 text-sm text-blue-800 flex items-start">
                        <AlertTriangle className="h-4 w-4 mr-2 mt-0.5" />
                        <span>
                            Node trạng thái Ready và Unreachable bị disable. Chỉ chọn các node Not bootstrapped hoặc Venv missing để bootstrap.
                        </span>
                    </div>
                </div>

                {/* Footer */}
                <div className="p-6 border-t border-gray-200 flex justify-end space-x-3">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleSubmit}
                        disabled={isLoading || selectableNodes.every(n => !selected[n.name])}
                        className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-400 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
                    >
                        {isLoading && <RefreshCw className="h-4 w-4 animate-spin mr-2" />}
                        Bootstrap selected nodes
                    </button>
                </div>
            </div>
        </div>
    );
};
