import React, { useState, useMemo, useEffect, useRef } from 'react';
import { benchmarkData, BenchmarkSection } from '../data/benchmarkData';
import { BenchmarkSectionCard } from './BenchmarkSectionCard';
import { Search, Filter, CheckCircle2, AlertCircle, Loader2, FileText, FileDown, ChevronDown, Wrench, Play, RefreshCw } from 'lucide-react';
import { benchmarkAPI } from '../services/benchmarkAPI';
import { RemediationModal } from './RemediationModal';
import { ScanResultsModal } from './ScanResultsModal';
import { k8sAPI, InventoryNode } from '../services/k8sAPI';
export const BenchmarkDashboard: React.FC = () => {
  const [sections, setSections] = useState<BenchmarkSection[]>(benchmarkData);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState<'all' | 'manual' | 'automated'>('all');
  const [isExportingResults, setIsExportingResults] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [scanProgress, setScanProgress] = useState(0);
  const [submitMessage, setSubmitMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);
  const [showFormatDropdown, setShowFormatDropdown] = useState(false);
  const [selectedFormat, setSelectedFormat] = useState<'html' | 'json' | 'pdf'>('html');
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Remediation State
  const [isRemediationModalOpen, setIsRemediationModalOpen] = useState(false);
  const [remediationCheckIds, setRemediationCheckIds] = useState<string[]>([]);
  const [isRemediating, setIsRemediating] = useState(false);
  const [remediationResults, setRemediationResults] = useState<any[] | null>(null);
  const [isScanResultsModalOpen, setIsScanResultsModalOpen] = useState(false);
  const [lastScanResults, setLastScanResults] = useState<any[]>([]);
  const [inventoryNodes, setInventoryNodes] = useState<InventoryNode[]>([]);
  const [selectedNodeName, setSelectedNodeName] = useState<string | undefined>(undefined);
  const [isLoadingNodes, setIsLoadingNodes] = useState(false);
  const clusterName = 'default';

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setShowFormatDropdown(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  const loadNodes = async (forceRefresh = false) => {
    try {
      setIsLoadingNodes(true);
      // Load from API endpoint which checks actual bootstrap status on nodes
      // Backend runs playbook to verify: /app/Kube-check/src, /app/Kube-check/venv exist
      // Uses cache (5min TTL) but always checks real status on nodes, not just inventory file
      const res = await k8sAPI.getInventory(clusterName, forceRefresh);
      const nodes = (res.nodes || []) as InventoryNode[];
      setInventoryNodes(nodes);
      // Preserve user selection; only set default when nothing selected yet
      if (!selectedNodeName) {
        const stored = localStorage.getItem('selectedNodeName') || undefined;
        const stillExists = stored && nodes.find(n => n.name === stored);
        if (stillExists) {
          setSelectedNodeName(stored);
        } else {
          const ready = nodes.find(n => n.status === 'ready');
          const fallback = ready || nodes[0];
          setSelectedNodeName(fallback?.name);
        }
      }
    } catch (err) {
      console.error('Failed to load nodes', err);
    } finally {
      setIsLoadingNodes(false);
    }
  };

  const refreshNodes = () => {
    loadNodes(true);
  };

  useEffect(() => {
    // Load nodes on mount or when clusterName changes
    // Use cache first (don't force refresh) to avoid slow playbook execution on every mount
    // Cache TTL is 5 minutes, which is sufficient for most cases
    loadNodes(false);

    // Listen for inventory updates (emitted after bootstrap) to refresh dropdown without full page reload
    // Only force refresh when explicitly notified (e.g., after bootstrap completes)
    const handleInventoryUpdated = () => loadNodes(true);
    window.addEventListener('inventory-updated', handleInventoryUpdated);

    return () => {
      window.removeEventListener('inventory-updated', handleInventoryUpdated);
    };
  }, [clusterName]);

  // Get selected node role
  const selectedNodeRole = useMemo(() => {
    if (!selectedNodeName) return null;
    const node = inventoryNodes.find(n => n.name === selectedNodeName);
    return node?.role?.toLowerCase() || null;
  }, [selectedNodeName, inventoryNodes]);

  // Determine which sections to show based on node role
  const getSectionsForRole = (role: string | null): string[] => {
    if (!role) return ['section1', 'section2', 'section3', 'section4', 'section5']; // Show all if no role

    if (role === 'master') {
      // Master nodes: Section 1 (Control Plane), 2 (etcd), 3 (Control Plane Config), 5 (Policies)
      // Policies can only be applied from master node or machine with kubeconfig
      return ['section1', 'section2', 'section3', 'section5'];
    } else if (role === 'worker') {
      // Worker nodes: Only Section 4 (Worker Nodes)
      // Policies (Section 5) cannot be applied from worker nodes (no kubectl access)
      return ['section4'];
    }

    // Default: show all
    return ['section1', 'section2', 'section3', 'section4', 'section5'];
  };

  const filteredSections = useMemo(() => {
    const allowedSectionIds = getSectionsForRole(selectedNodeRole);

    return sections
      .filter(section => allowedSectionIds.includes(section.id))
      .map(section => ({
        ...section,
        items: section.items.filter(item => {
          const matchesSearch = item.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
            item.description.toLowerCase().includes(searchTerm.toLowerCase()) ||
            item.id.toLowerCase().includes(searchTerm.toLowerCase());

          const matchesFilter = filterType === 'all' ||
            (filterType === 'manual' && item.type === 'Manual') ||
            (filterType === 'automated' && item.type === 'Automated');

          return matchesSearch && matchesFilter;
        })
      })).filter(section => section.items.length > 0);
  }, [sections, searchTerm, filterType, selectedNodeRole]);

  // Calculate totals based on filtered sections (respecting role filter)
  const totalItems = filteredSections.reduce((acc, section) => acc + section.items.length, 0);
  const selectedItems = filteredSections.reduce((acc, section) =>
    acc + section.items.filter(item => item.selected).length, 0);

  // Get failed items that are selected (from filtered sections)
  const selectedFailedItems = filteredSections.flatMap(section =>
    section.items.filter(item => item.selected && item.status === 'FAIL')
  );

  const handleToggleItem = (itemId: string) => {
    setSections(prevSections =>
      prevSections.map(section => ({
        ...section,
        items: section.items.map(item =>
          item.id === itemId ? { ...item, selected: !item.selected } : item
        )
      }))
    );
  };

  const handleToggleSection = (sectionId: string) => {
    setSections(prevSections =>
      prevSections.map(section => {
        if (section.id === sectionId) {
          const allSelected = section.items.every(item => item.selected);
          return {
            ...section,
            items: section.items.map(item => ({ ...item, selected: !allSelected }))
          };
        }
        return section;
      })
    );
  };

  const handleSelectAll = () => {
    const allSelected = selectedItems === totalItems;
    const allowedSectionIds = getSectionsForRole(selectedNodeRole);

    setSections(prevSections =>
      prevSections.map(section => {
        // Only modify sections that are visible (filtered by role)
        if (allowedSectionIds.includes(section.id)) {
          return {
            ...section,
            items: section.items.map(item => ({ ...item, selected: !allSelected }))
          };
        }
        // Keep other sections unchanged
        return section;
      })
    );
  };

  // Remediation Handlers
  const handleRemediateSingle = (checkId: string) => {
    setRemediationCheckIds([checkId]);
    setRemediationResults(null);
    setIsRemediationModalOpen(true);
  };

  const handleRemediateSelected = () => {
    const ids = selectedFailedItems.map(item => item.id);
    if (ids.length === 0) return;

    setRemediationCheckIds(ids);
    setRemediationResults(null);
    setIsRemediationModalOpen(true);
  };

  const confirmRemediation = async () => {
    setIsRemediating(true);
    try {
      const response = await benchmarkAPI.remediateCheck(remediationCheckIds, {
        clusterName,
        nodeName: selectedNodeName
      });

      if (response.success) {
        setRemediationResults(response.results);

        // Update local state based on VERIFICATION results
        const passedIds = response.results
          .filter((r: any) =>
            // Mark as PASS if verification says PASS, or any remediation action returns success/PASS
            r.status === 'PASS' || r.success === true
          )
          .map((r: any) => r.checkId);

        const failedIds = response.results
          .filter((r: any) => r.status && r.status !== 'PASS')
          .map((r: any) => r.checkId);

        if (passedIds.length > 0 || failedIds.length > 0) {
          setSections(prevSections =>
            prevSections.map(section => ({
              ...section,
              items: section.items.map(item => {
                if (passedIds.includes(item.id)) {
                  return { ...item, status: 'PASS' };
                }
                if (failedIds.includes(item.id)) {
                  // Keep it as FAIL but maybe add a note? standardizing to FAIL is fine for now
                  return { ...item, status: 'FAIL' };
                }
                return item;
              })
            }))
          );
        }

        // Dispatch event to notify dashboard to refresh
        // This allows DashboardPage to automatically update after remediation
        window.dispatchEvent(new CustomEvent('remediation-complete', {
          detail: {
            checkIds: remediationCheckIds,
            results: response.results,
            passedIds,
            failedIds,
            nodeName: selectedNodeName,
            clusterName: clusterName
          }
        }));
      } else {
        setSubmitMessage({ type: 'error', text: 'Remediation failed to start' });
        setIsRemediationModalOpen(false);
      }
    } catch (error) {
      console.error('Remediation error:', error);
      setSubmitMessage({
        type: 'error',
        text: 'Failed to execute remediation: ' + (error instanceof Error ? error.message : String(error))
      });
      setIsRemediationModalOpen(false);
    } finally {
      setIsRemediating(false);
    }
  };

  // Xóa hàm handleExport vì không cần thiết nữa
  // const handleExport = () => {
  //   const selectedControls = sections.flatMap(section =>
  //     section.items.filter(item => item.selected).map(item => ({
  //       section: section.title,
  //       id: item.id,
  //       title: item.title,
  //       description: item.description,
  //       type: item.type
  //     }))
  //   );

  //   const dataStr = JSON.stringify(selectedControls, null, 2);
  //   const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);

  //   const exportFileDefaultName = 'kubernetes-cis-benchmark-selection.json';

  //   const linkElement = document.createElement('a');
  //   linkElement.setAttribute('href', dataUri);
  //   linkElement.setAttribute('download', exportFileDefaultName);
  //   linkElement.click();
  // };

  const handleRunScan = async () => {
    const selectedControls = sections.flatMap(section =>
      section.items.filter(item => item.selected)
    );

    if (selectedControls.length === 0) {
      setSubmitMessage({ type: 'error', text: 'Please select at least one benchmark item to scan' });
      return;
    }

    setIsScanning(true);
    setScanProgress(0);
    setSubmitMessage(null);

    try {
      // 1. Submit and Start Scan
      const { scanId } = await benchmarkAPI.submitAndScan(
        selectedControls,
        {},
        {},
        { clusterName, nodeName: selectedNodeName }
      );

      // 2. Poll for results
      await benchmarkAPI.pollScanStatus(scanId, (progress, results) => {
        setScanProgress(progress);
      });

      // 3. Get final results
      const finalStatus = await benchmarkAPI.getScanStatus(scanId);

      if (finalStatus.data.status === 'completed') {
        // Update local state with scan results
        const scanResults = finalStatus.data.results;

        setSections(prevSections =>
          prevSections.map(section => ({
            ...section,
            items: section.items.map(item => {
              const result = scanResults.find((r: any) => r.itemId === item.id);
              if (result) {
                return {
                  ...item,
                  status: result.status, // 'PASS' or 'FAIL'
                  remediation: result.remediation
                };
              }
              return item;
            })
          }))
        );

        const failedCount = scanResults.filter((r: any) => r.status === 'FAIL').length;
        setSubmitMessage({
          type: failedCount > 0 ? 'error' : 'success',
          text: `Scan completed! Found ${failedCount} failed checks.`
        });

        // Dispatch event to notify dashboard to refresh
        // This allows DashboardPage to automatically update after scan
        window.dispatchEvent(new CustomEvent('scan-complete', {
          detail: {
            scanId,
            results: scanResults,
            failedCount
          }
        }));

        // Open results modal
        setLastScanResults(scanResults);
        setIsScanResultsModalOpen(true);
      } else {
        throw new Error('Scan failed to complete');
      }

    } catch (error) {
      console.error('Scan error:', error);
      setSubmitMessage({
        type: 'error',
        text: 'Failed to run scan: ' + (error instanceof Error ? error.message : String(error))
      });
    } finally {
      setIsScanning(false);
      setScanProgress(0);
    }
  };

  const handleExportScanResults = async (format: 'html' | 'json' | 'pdf' = selectedFormat) => {
    // Check if there are scan results to export
    if (!lastScanResults || lastScanResults.length === 0) {
      setSubmitMessage({
        type: 'error',
        text: 'No scan results available. Please run a scan first to export results.'
      });
      return;
    }

    setIsExportingResults(true);
    setSubmitMessage(null);
    setShowFormatDropdown(false);

    try {
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      const nodeInfo = selectedNodeName ? `-${selectedNodeName}` : '';
      const filename = `scan-results${nodeInfo}-${timestamp}.${format}`;

      setSubmitMessage({
        type: 'success',
        text: `Exporting scan results as ${format.toUpperCase()}... Please wait.`
      });

      // Export scan results
      const response = await benchmarkAPI.exportScanResults(lastScanResults, format, filename);

      console.log('✅ Scan results exported:', response);

      setSubmitMessage({
        type: 'success',
        text: `Scan results exported successfully as ${format.toUpperCase()}! (${lastScanResults.length} checks)`
      });

    } catch (error) {
      console.error('❌ Failed to export scan results:', error);
      setSubmitMessage({
        type: 'error',
        text: 'Failed to export scan results: ' + (error instanceof Error ? error.message : String(error))
      });
    } finally {
      setIsExportingResults(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col gap-6">
            <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6">
              <div className="space-y-3">
                <div className="inline-flex items-center px-3 py-1 text-xs font-semibold rounded-full bg-blue-200 text-blue-800 border border-blue-300 w-fit">
                  Kubernetes Security
                </div>
                <div className="flex items-center gap-3 flex-wrap">
                  <h1 className="text-3xl font-semibold tracking-tight text-gray-900">Kubernetes CIS Benchmark</h1>
                  <span className="px-3 py-1 rounded-full bg-gray-100 text-sm text-gray-700 border border-gray-200">
                    {selectedItems} of {totalItems} selected
                  </span>
                </div>
                <p className="text-gray-600 max-w-2xl">
                  Select and manage Kubernetes security compliance checks for your cluster. Run scans, remediate issues, and export professional reports.
                </p>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 w-full lg:w-auto min-w-0">
                <div className="rounded-2xl bg-gray-100 border border-gray-300 px-4 py-3 shadow-sm min-w-0">
                  <p className="text-xs uppercase tracking-wide text-gray-600">Selected</p>
                  <p className="text-lg font-semibold text-gray-900">{selectedItems}</p>
                </div>
                <div className="rounded-2xl bg-red-100 border border-red-300 px-4 py-3 shadow-sm min-w-0">
                  <p className="text-xs uppercase tracking-wide text-red-800">Failed</p>
                  <p className="text-lg font-semibold text-red-800">{selectedFailedItems.length}</p>
                </div>
                <div className="rounded-2xl bg-sky-100 border border-sky-300 px-4 py-3 shadow-sm min-w-0">
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-xs uppercase tracking-wide text-sky-800">Node</p>
                    <button
                      onClick={refreshNodes}
                      disabled={isLoadingNodes}
                      className="p-1 hover:bg-sky-200 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      title="Refresh node status"
                    >
                      <RefreshCw className={`h-3 w-3 text-sky-700 ${isLoadingNodes ? 'animate-spin' : ''}`} />
                    </button>
                  </div>
                  <select
                    value={selectedNodeName || ''}
                    onChange={(e) => {
                      const next = e.target.value || undefined;
                      setSelectedNodeName(next);
                      if (next) {
                        localStorage.setItem('selectedNodeName', next);
                      } else {
                        localStorage.removeItem('selectedNodeName');
                      }
                    }}
                    disabled={isLoadingNodes || inventoryNodes.length === 0}
                    className="w-full mt-1 bg-white border border-sky-200 rounded-lg text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-sky-500 py-2 px-2 truncate"
                    title={selectedNodeName ? inventoryNodes.find(n => n.name === selectedNodeName)?.name : ''}
                  >
                    {isLoadingNodes && <option>Loading...</option>}
                    {!isLoadingNodes && inventoryNodes.length === 0 && <option value="">No nodes</option>}
                    {!isLoadingNodes && inventoryNodes.map((n) => {
                      // Show status for non-ready nodes
                      const statusDisplay = n.status && n.status !== 'ready' ? ` (${n.status})` : '';
                      // Only disable nodes that are not ready (unreachable/not_bootstrapped can be selected for bootstrap, but not for scan)
                      // For scan, only ready nodes can be used
                      const disabled = !!(n.status && n.status !== 'ready');
                      return (
                        <option
                          key={n.name}
                          value={n.name}
                          disabled={disabled}
                          title={`${n.name}${statusDisplay}${disabled ? ' - Bootstrap required before scan' : ''}`}
                        >
                          {n.name}{statusDisplay}
                        </option>
                      );
                    })}
                  </select>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              <button
                onClick={handleRunScan}
                disabled={selectedItems === 0 || isScanning || (!selectedNodeName && inventoryNodes.length > 0)}
                className="w-full flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-blue-700 text-white font-semibold shadow-md shadow-blue-200/70 hover:bg-blue-800 transition-colors disabled:opacity-60 disabled:cursor-not-allowed min-w-0"
              >
                {isScanning ? <Loader2 className="h-4 w-4 animate-spin flex-shrink-0" /> : <Play className="h-4 w-4 flex-shrink-0" />}
                <span className="truncate">{isScanning ? `Scanning ${scanProgress}%...` : 'Run Scan'}</span>
              </button>

              <button
                onClick={handleRemediateSelected}
                disabled={selectedFailedItems.length === 0}
                className="w-full flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-red-600 text-white font-semibold shadow-md shadow-red-200/70 hover:bg-red-700 transition-colors disabled:opacity-60 disabled:cursor-not-allowed min-w-0"
              >
                <Wrench className="h-4 w-4 flex-shrink-0" />
                <span className="truncate">Fix Selected ({selectedFailedItems.length})</span>
              </button>

              <button
                onClick={handleSelectAll}
                className="w-full flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-blue-600 text-white font-semibold shadow-md shadow-blue-200/70 hover:bg-blue-700 transition-colors min-w-0"
              >
                <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
                <span className="truncate">{selectedItems === totalItems ? 'Deselect All' : 'Select All'}</span>
              </button>

              <div className="relative w-full min-w-0" ref={dropdownRef}>
                <button
                  onClick={() => setShowFormatDropdown(!showFormatDropdown)}
                  disabled={!lastScanResults || lastScanResults.length === 0 || isExportingResults}
                  className="w-full flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-teal-600 text-white font-semibold shadow-md shadow-teal-200/70 hover:bg-teal-700 transition-colors disabled:opacity-60 disabled:cursor-not-allowed min-w-0"
                  title={!lastScanResults || lastScanResults.length === 0 ? 'Run a scan first to export results' : 'Export scan results'}
                >
                  {isExportingResults ? <Loader2 className="h-4 w-4 animate-spin flex-shrink-0" /> : <FileDown className="h-4 w-4 flex-shrink-0" />}
                  <span className="truncate">
                    {isExportingResults
                      ? `Exporting ${selectedFormat.toUpperCase()}...`
                      : `Export Scan Results (${selectedFormat.toUpperCase()})`
                    }
                  </span>
                  <ChevronDown className="h-4 w-4 flex-shrink-0" />
                </button>

                {showFormatDropdown && !isExportingResults && (
                  <div className="absolute top-full left-0 mt-2 w-48 bg-white border border-gray-200 rounded-xl shadow-2xl z-10 overflow-hidden">
                    <button
                      onClick={() => {
                        setSelectedFormat('html');
                        handleExportScanResults('html');
                      }}
                      className="flex items-center gap-2 w-full px-4 py-3 text-left hover:bg-gray-50"
                    >
                      <FileText className="h-4 w-4 text-orange-500" />
                      <span className="text-gray-800">Export as HTML</span>
                    </button>
                    <button
                      onClick={() => {
                        setSelectedFormat('pdf');
                        handleExportScanResults('pdf');
                      }}
                      className="flex items-center gap-2 w-full px-4 py-3 text-left hover:bg-gray-50 border-t border-gray-100"
                    >
                      <FileText className="h-4 w-4 text-red-500" />
                      <span className="text-gray-800">Export as PDF</span>
                    </button>
                    <button
                      onClick={() => {
                        setSelectedFormat('json');
                        handleExportScanResults('json');
                      }}
                      className="flex items-center gap-2 w-full px-4 py-3 text-left hover:bg-gray-50 border-t border-gray-100"
                    >
                      <FileDown className="h-4 w-4 text-blue-500" />
                      <span className="text-gray-800">Export as JSON</span>
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Filters and Search */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* Submit Message */}
        {submitMessage && (
          <div className={`mb-6 p-4 rounded-lg border ${submitMessage.type === 'success'
            ? 'bg-green-50 border-green-200 text-green-800'
            : 'bg-red-50 border-red-200 text-red-800'
            }`}>
            <div className="flex items-center">
              {submitMessage.type === 'success' ? (
                <CheckCircle2 className="h-5 w-5 mr-2" />
              ) : (
                <AlertCircle className="h-5 w-5 mr-2" />
              )}
              <span className="text-sm font-medium">{submitMessage.text}</span>
              <button
                onClick={() => setSubmitMessage(null)}
                className="ml-auto text-sm underline hover:no-underline"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        <div className="bg-white rounded-2xl border border-gray-200 p-6 mb-6 shadow-sm">
          <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
            {/* Search */}
            <div className="flex-1">
              <div className="relative">
                <Search className="absolute left-3 top-3 h-4 w-4 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search controls by ID, title, or description..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="w-full pl-10 pr-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500 focus:border-transparent bg-gray-50"
                />
              </div>
            </div>

            {/* Filter */}
            <div className="w-full lg:w-64">
              <div className="relative">
                <Filter className="absolute left-3 top-3 h-4 w-4 text-gray-400" />
                <select
                  value={filterType}
                  onChange={(e) => setFilterType(e.target.value as 'all' | 'manual' | 'automated')}
                  className="w-full pl-10 pr-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500 focus:border-transparent appearance-none bg-white"
                >
                  <option value="all">All Types</option>
                  <option value="automated">Automated</option>
                  <option value="manual">Manual</option>
                </select>
              </div>
            </div>
          </div>

          {/* Stats */}
          <div className="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="flex items-center gap-3 rounded-xl border border-gray-300 bg-gray-100 px-4 py-3">
              <div className="w-10 h-10 rounded-full bg-gray-200 text-gray-900 flex items-center justify-center font-semibold">
                {filteredSections.reduce((acc, section) => acc + section.items.length, 0)}
              </div>
              <div>
                <p className="text-xs text-gray-700">Total controls</p>
                <p className="text-sm font-semibold text-gray-900">Coverage overview</p>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-xl border border-teal-300 bg-teal-100 px-4 py-3">
              <div className="w-10 h-10 rounded-full bg-teal-200 text-teal-800 flex items-center justify-center font-semibold">
                {filteredSections.reduce((acc, section) =>
                  acc + section.items.filter(item => item.type === 'Automated').length, 0)}
              </div>
              <div>
                <p className="text-xs text-teal-800">Automated</p>
                <p className="text-sm font-semibold text-teal-900">Ready to scan</p>
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-xl border border-amber-300 bg-amber-100 px-4 py-3">
              <div className="w-10 h-10 rounded-full bg-amber-200 text-amber-800 flex items-center justify-center font-semibold">
                {filteredSections.reduce((acc, section) =>
                  acc + section.items.filter(item => item.type === 'Manual').length, 0)}
              </div>
              <div>
                <p className="text-xs text-amber-700">Manual</p>
                <p className="text-sm font-semibold text-amber-900">Requires review</p>
              </div>
            </div>
          </div>
        </div>

        {/* Sections */}
        <div className="space-y-6">
          {filteredSections.length > 0 ? (
            filteredSections.map((section) => (
              <BenchmarkSectionCard
                key={section.id}
                section={section}
                onToggleItem={handleToggleItem}
                onToggleSection={handleToggleSection}
                onRemediate={handleRemediateSingle}
              />
            ))
          ) : (
            <div className="text-center py-12">
              <AlertCircle className="mx-auto h-12 w-12 text-gray-400" />
              <h3 className="mt-2 text-sm font-medium text-gray-900">No controls found</h3>
              <p className="mt-1 text-sm text-gray-500">
                Try adjusting your search terms or filters.
              </p>
            </div>
          )}
        </div>
      </div>


      {/* Remediation Modal */}
      <RemediationModal
        isOpen={isRemediationModalOpen}
        onClose={() => setIsRemediationModalOpen(false)}
        onConfirm={confirmRemediation}
        checkIds={remediationCheckIds}
        checkDetails={remediationCheckIds.map(id => {
          const item = sections.flatMap(s => s.items).find(i => i.id === id);
          return { checkId: id, remediation: item?.remediation };
        })}
        isLoading={isRemediating}
        results={remediationResults}
      />

      <ScanResultsModal
        isOpen={isScanResultsModalOpen}
        onClose={() => setIsScanResultsModalOpen(false)}
        results={lastScanResults}
      />
    </div >
  );
};
