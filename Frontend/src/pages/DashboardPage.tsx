import React, { useEffect, useState } from 'react';
import { CheckCircle2, AlertCircle, ShieldAlert, Activity, Clock, Wrench } from 'lucide-react';
import { benchmarkAPI } from '../services/benchmarkAPI';

interface ScanHistory {
  id: string;
  status: 'running' | 'completed' | 'failed';
  timestamp?: string;
  startTime?: string;
  endTime?: string;
  results?: any[];
  nodeName?: string;
  clusterName?: string;
}

export const DashboardPage: React.FC = () => {
  const [scanHistory, setScanHistory] = useState<ScanHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [remediationEvents, setRemediationEvents] = useState<any[]>([]); // Store remediation events from database
  const [stats, setStats] = useState({
    overallScore: 0,
    totalChecks: 0,
    passedChecks: 0,
    failedChecks: 0,
    warningChecks: 0,
    remediatedChecks: 0,
  });

  useEffect(() => {
    loadDashboardData();

    // Listen for remediation completion events to refresh dashboard
    const handleRemediationComplete = () => {
      console.log('Dashboard: Remediation completed, refreshing data...');
      // Small delay to ensure backend has saved to database
      setTimeout(() => {
        loadDashboardData();
      }, 2000);
    };

    window.addEventListener('remediation-complete', handleRemediationComplete);
    window.addEventListener('scan-complete', handleRemediationComplete);

    return () => {
      window.removeEventListener('remediation-complete', handleRemediationComplete);
      window.removeEventListener('scan-complete', handleRemediationComplete);
    };
  }, []);

  const loadDashboardData = async () => {
    try {
      setLoading(true);

      // Load scan history
      const response = await benchmarkAPI.getScanHistory(10);

      // Load remediation events from database
      const remediationResponse = await benchmarkAPI.getAuditEvents({
        limit: 100,
        type: 'remediation'
      });

      if (remediationResponse.success && Array.isArray(remediationResponse.data)) {
        // Filter successful remediations (status = SUCCESS and verifyResult.status = PASS)
        const successfulRemediations = remediationResponse.data.filter((event: any) => {
          const status = event.status?.toUpperCase();
          const details = event.details || {};
          const verifyResult = details.verifyResult || {};
          const verifyStatus = verifyResult.status?.toUpperCase();

          // Include if status is SUCCESS and verifyResult.status is PASS
          // Also check post_check_status for backward compatibility
          const postStatus = details.post_check_status?.toUpperCase();

          return status === 'SUCCESS' && (verifyStatus === 'PASS' || postStatus === 'PASS');
        });

        console.log('Dashboard: Loaded remediation events from database:', successfulRemediations.length);
        setRemediationEvents(successfulRemediations);
      } else {
        console.log('Dashboard: No remediation events found or error loading');
        setRemediationEvents([]);
      }

      if (response.success && response.data) {
        // Filter and process scans
        const allScans = Array.isArray(response.data) ? response.data : [];

        // Debug: Log all scans to see what we're working with
        if (allScans.length > 0) {
          console.log('Dashboard: Found scans in backend:', allScans.length);
          allScans.forEach((scan: ScanHistory, idx: number) => {
            console.log(`  Scan ${idx + 1}:`, {
              id: scan.id?.substring(0, 8),
              status: scan.status,
              resultsCount: scan.results?.length || 0,
              nodeName: scan.nodeName,
              hasResults: !!scan.results,
              isArray: Array.isArray(scan.results)
            });
          });
        }

        const scans = allScans
          .filter((scan: ScanHistory) => {
            // Include completed scans with results
            const hasResults = scan.results && Array.isArray(scan.results);
            const hasNonEmptyResults = hasResults && (scan.results?.length ?? 0) > 0;
            const isCompleted = scan.status === 'completed';

            const shouldInclude = isCompleted && hasNonEmptyResults;

            if (!shouldInclude && allScans.length > 0) {
              console.log(`Dashboard: Excluding scan ${scan.id?.substring(0, 8)}:`, {
                isCompleted,
                hasResults,
                hasNonEmptyResults,
                resultsLength: scan.results?.length || 0
              });
            }

            // Only include completed scans with non-empty results
            return shouldInclude;
          })
          .map((scan: ScanHistory) => {
            // Ensure timestamp is valid
            let timestamp = scan.timestamp;
            if (!timestamp && scan.startTime) {
              timestamp = scan.startTime;
            }
            if (!timestamp && scan.endTime) {
              timestamp = scan.endTime;
            }
            return { ...scan, timestamp: timestamp || new Date().toISOString() };
          })
          .sort((a: ScanHistory, b: ScanHistory) => {
            const timestampA = a.timestamp || a.startTime || a.endTime || new Date().toISOString();
            const timestampB = b.timestamp || b.startTime || b.endTime || new Date().toISOString();
            const timeA = new Date(timestampA).getTime();
            const timeB = new Date(timestampB).getTime();
            // Handle invalid dates
            if (isNaN(timeA) || isNaN(timeB)) return 0;
            return timeB - timeA;
          });

        console.log('Dashboard: After filtering, scans count:', scans.length);
        setScanHistory(scans);

        // Calculate statistics from the most recent scan
        if (scans.length > 0) {
          const latestScan = scans[0];
          const results = latestScan.results || [];

          const total = results.length;
          const passed = results.filter((r: any) => r.status === 'PASS').length;
          const failed = results.filter((r: any) => r.status === 'FAIL' &&
            !(r.type === 'Manual' || (r.title && r.title.includes('(Manual)')))).length;
          const warnings = results.filter((r: any) =>
            r.status === 'WARN' ||
            (r.status === 'FAIL' && (r.type === 'Manual' || (r.title && r.title.includes('(Manual)'))))
          ).length;

          // Calculate remediated checks from database (remediation events)
          // Count unique remediated checks from remediation events
          const uniqueRemediated = new Set<string>();
          remediationEvents.forEach((event: any) => {
            if (event.checkId) {
              uniqueRemediated.add(event.checkId);
            }
          });

          // Also count from scan comparison as fallback
          if (scans.length > 1) {
            const previousScan = scans[1];
            const previousResults = previousScan.results || [];

            // Create maps for easy lookup
            const latestMap = new Map<string, any>(results.map((r: any) => [r.itemId || r.id, r]));
            const previousMap = new Map<string, any>(previousResults.map((r: any) => [r.itemId || r.id, r]));

            // Count checks that changed from FAIL to PASS (likely remediated)
            latestMap.forEach((latestResult: any, checkId: string) => {
              if (latestResult.status === 'PASS') {
                const previousResult = previousMap.get(checkId) as any;
                if (previousResult && previousResult.status === 'FAIL') {
                  // Exclude manual checks
                  const isManual = latestResult.type === 'Manual' ||
                    (latestResult.title && latestResult.title.includes('(Manual)'));
                  if (!isManual) {
                    uniqueRemediated.add(checkId);
                  }
                }
              }
            });
          }

          const remediated = uniqueRemediated.size;

          const score = total > 0 ? Math.round((passed / total) * 100) : 0;

          setStats({
            overallScore: score,
            totalChecks: total,
            passedChecks: passed,
            failedChecks: failed,
            warningChecks: warnings,
            remediatedChecks: remediated,
          });
        }
      }
    } catch (error) {
      console.error('Failed to load dashboard data:', error);
      // Set empty state on error
      setScanHistory([]);
    } finally {
      setLoading(false);
    }
  };

  const formatTimeAgo = (timestamp: string) => {
    if (!timestamp) return 'Unknown time';

    try {
      const now = new Date();
      // If timestamp doesn't have timezone info, treat it as UTC
      // This handles old timestamps from backend that may not have timezone
      let timeStr = timestamp.trim();
      // Check if timestamp has timezone indicator (Z, +HH:MM, or -HH:MM)
      const hasTimezone = timeStr.includes('Z') ||
        /[+-]\d{2}:\d{2}$/.test(timeStr) ||
        /[+-]\d{4}$/.test(timeStr);

      if (!hasTimezone) {
        // No timezone indicator, append 'Z' to treat as UTC
        timeStr = timeStr + 'Z';
      }
      const time = new Date(timeStr);

      // Check if date is valid
      if (isNaN(time.getTime())) {
        return 'Invalid date';
      }

      const diffMs = now.getTime() - time.getTime();

      // Check if diff is valid
      if (isNaN(diffMs) || diffMs < 0) {
        return 'Just now';
      }

      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMs / 3600000);
      const diffDays = Math.floor(diffMs / 86400000);

      if (diffMins < 1) return 'Just now';
      if (diffMins < 60) return `${diffMins} minute${diffMins > 1 ? 's' : ''} ago`;
      if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
      if (diffDays < 30) return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;

      const diffMonths = Math.floor(diffDays / 30);
      if (diffMonths < 12) return `${diffMonths} month${diffMonths > 1 ? 's' : ''} ago`;

      const diffYears = Math.floor(diffMonths / 12);
      return `${diffYears} year${diffYears > 1 ? 's' : ''} ago`;
    } catch (error) {
      console.error('Error formatting time:', error, timestamp);
      return 'Unknown time';
    }
  };

  const getTopFailingChecks = () => {
    if (scanHistory.length === 0) return [];

    // Get failing checks from the 5 most recent scans
    const recentScans = scanHistory.slice(0, 5);
    const failingChecks: any[] = [];

    recentScans.forEach((scan) => {
      const results = scan.results || [];
      const nodeName = scan.nodeName || 'Unknown';
      const timestamp = scan.timestamp || scan.startTime || scan.endTime || '';

      results
        .filter((r: any) => r.status === 'FAIL' &&
          !(r.type === 'Manual' || (r.title && r.title.includes('(Manual)'))))
        .forEach((result: any) => {
          // Avoid duplicates by checking if same checkId from same node already exists
          const existingIndex = failingChecks.findIndex(
            (fc: any) => (fc.itemId || fc.id) === (result.itemId || result.id) && fc.nodeName === nodeName
          );

          if (existingIndex === -1) {
            failingChecks.push({
              ...result,
              nodeName,
              timestamp,
              scanId: scan.id,
            });
          }
        });
    });

    // Sort by timestamp (most recent first) and return top 5
    return failingChecks
      .sort((a, b) => {
        const timeA = new Date(a.timestamp || '').getTime();
        const timeB = new Date(b.timestamp || '').getTime();
        return timeB - timeA;
      })
      .slice(0, 5);
  };

  const getRemediatedChecks = () => {
    const remediated: any[] = [];
    const seenRemediations = new Set<string>(); // Track to avoid duplicates

    // First, add remediated checks from database (remediation events)
    remediationEvents.forEach((event: any) => {
      const checkId = event.checkId;
      if (!checkId) return; // Skip if no checkId

      const nodeName = event.nodeName || 'Unknown';
      const uniqueKey = `${nodeName}:${checkId}`;

      if (!seenRemediations.has(uniqueKey)) {
        seenRemediations.add(uniqueKey);

        // Get title from action or details
        let title = event.action || `Check ${checkId}`;
        const details = event.details || {};

        // Try to get check text from verifyResult or remediationResult
        if (details.verifyResult && details.verifyResult.details && details.verifyResult.details.text) {
          title = details.verifyResult.details.text;
        } else if (details.remediationResult && details.remediationResult.text) {
          title = details.remediationResult.text;
        } else if (details.check_text) {
          title = details.check_text;
        }

        remediated.push({
          itemId: checkId,
          id: checkId,
          title: title,
          status: 'PASS',
          nodeName: nodeName,
          timestamp: event.timestamp || new Date().toISOString(),
          scanId: event.id || `remediation-${checkId}`,
          previousStatus: details.pre_check_status || 'FAIL',
          isFromRemediation: true,
          remediationDetails: details,
        });
      }
    });

    // Then, compare scans in pairs to find remediated checks from scan history
    // This is a fallback for cases where remediation wasn't logged to audit
    if (scanHistory.length >= 2) {
      const recentScans = scanHistory.slice(0, 5);

      // Compare each scan with the previous one
      for (let i = 0; i < recentScans.length - 1; i++) {
        const currentScan = recentScans[i];
        const previousScan = recentScans[i + 1];

        // Only compare scans from the same node
        const currentNodeName = currentScan.nodeName || 'Unknown';
        const previousNodeName = previousScan.nodeName || 'Unknown';

        if (currentNodeName !== previousNodeName) continue;

        const currentResults = currentScan.results || [];
        const previousResults = previousScan.results || [];

        // Create maps for easy lookup
        const currentMap = new Map<string, any>(currentResults.map((r: any) => [r.itemId || r.id, r]));
        const previousMap = new Map<string, any>(previousResults.map((r: any) => [r.itemId || r.id, r]));

        currentMap.forEach((currentResult: any, checkId: string) => {
          if (currentResult.status === 'PASS') {
            const previousResult = previousMap.get(checkId) as any;
            if (previousResult && previousResult.status === 'FAIL') {
              // Exclude manual checks
              const isManual = currentResult.type === 'Manual' ||
                (currentResult.title && currentResult.title.includes('(Manual)'));
              if (!isManual) {
                // Create unique key: nodeName + checkId
                const uniqueKey = `${currentNodeName}:${checkId}`;
                // Only add if not already in database remediation events
                if (!seenRemediations.has(uniqueKey)) {
                  seenRemediations.add(uniqueKey);
                  remediated.push({
                    ...currentResult,
                    nodeName: currentNodeName,
                    timestamp: currentScan.timestamp || currentScan.startTime || currentScan.endTime || '',
                    scanId: currentScan.id,
                    previousStatus: previousResult.status,
                  });
                }
              }
            }
          }
        });
      }
    }

    // Sort by timestamp (most recent first) and return top 5
    return remediated
      .sort((a, b) => {
        const timeA = new Date(a.timestamp || '').getTime();
        const timeB = new Date(b.timestamp || '').getTime();
        return timeB - timeA;
      })
      .slice(0, 5);
  };

  const getManualChecks = () => {
    if (scanHistory.length === 0) return [];

    // Get manual checks from the 5 most recent scans
    const recentScans = scanHistory.slice(0, 5);
    const manualChecks: any[] = [];

    recentScans.forEach((scan) => {
      const results = scan.results || [];
      const nodeName = scan.nodeName || 'Unknown';
      const timestamp = scan.timestamp || scan.startTime || scan.endTime || '';

      results
        .filter((r: any) =>
          (r.type === 'Manual' || (r.title && r.title.includes('(Manual)'))) &&
          (r.status === 'FAIL' || r.status === 'WARN')
        )
        .forEach((result: any) => {
          // Avoid duplicates by checking if same checkId from same node already exists
          const existingIndex = manualChecks.findIndex(
            (mc: any) => (mc.itemId || mc.id) === (result.itemId || result.id) && mc.nodeName === nodeName
          );

          if (existingIndex === -1) {
            manualChecks.push({
              ...result,
              nodeName,
              timestamp,
              scanId: scan.id,
            });
          } else {
            // If duplicate exists, keep the one with the most recent timestamp
            const existing = manualChecks[existingIndex];
            const existingTime = new Date(existing.timestamp || '').getTime();
            const newTime = new Date(timestamp || '').getTime();
            if (!isNaN(newTime) && !isNaN(existingTime) && newTime > existingTime) {
              // Replace with newer version
              manualChecks[existingIndex] = {
                ...result,
                nodeName,
                timestamp,
                scanId: scan.id,
              };
            }
          }
        });
    });

    // Helper function to parse check ID for sorting (e.g., "1.2.3" -> [1, 2, 3])
    const parseCheckId = (checkId: string): number[] => {
      if (!checkId) return [0];
      const parts = checkId.split('.').map(part => {
        const num = parseInt(part, 10);
        return isNaN(num) ? 0 : num;
      });
      return parts.length > 0 ? parts : [0];
    };

    // Sort by check ID number (descending: 5.x.x lên đầu, 1.x.x xuống dưới)
    // Đây là ngược với report (report sắp xếp 1.x.x trước, 5.x.x sau)
    return manualChecks
      .sort((a, b) => {
        const idA = parseCheckId(a.itemId || a.id || '');
        const idB = parseCheckId(b.itemId || b.id || '');

        // Compare each part of the ID (descending order - số lớn hơn lên đầu)
        for (let i = 0; i < Math.max(idA.length, idB.length); i++) {
          const partA = idA[i] || 0;
          const partB = idB[i] || 0;
          if (partA !== partB) {
            return partB - partA; // Descending order (5.x.x before 1.x.x)
          }
        }

        // If IDs are equal, sort by timestamp (most recent first)
        const timeA = new Date(a.timestamp || '').getTime();
        const timeB = new Date(b.timestamp || '').getTime();
        if (!isNaN(timeA) && !isNaN(timeB)) {
          return timeB - timeA;
        }

        return 0;
      })
      .slice(0, 5);
  };

  const topFailing = getTopFailingChecks();
  const remediatedChecks = getRemediatedChecks();
  const manualChecks = getManualChecks();

  if (loading) {
    return (
      <div className="p-8">
        <div className="flex items-center justify-center h-64">
          <Activity className="h-8 w-8 animate-spin text-blue-500" />
        </div>
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Security Overview</h1>
        <button
          onClick={loadDashboardData}
          className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
        >
          Refresh
        </button>
      </div>

      {scanHistory.length === 0 ? (
        <div className="bg-white p-12 rounded-xl shadow-sm border border-gray-200 text-center">
          <Activity className="h-12 w-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-gray-900 mb-2">No Scan Data Available</h3>
          <p className="text-gray-500 mb-4">Run your first scan to see security overview and statistics.</p>
          <div className="mt-6 p-4 bg-blue-50 rounded-lg border border-blue-200 text-left max-w-md mx-auto">
            <p className="text-sm text-blue-900 font-medium mb-2">💡 Quick Start:</p>
            <ol className="text-sm text-blue-800 list-decimal list-inside space-y-1">
              <li>Go to <strong>"Scan & Fix"</strong> page</li>
              <li>Select benchmark checks to scan</li>
              <li>Choose a node (if using remote mode)</li>
              <li>Click <strong>"Run Scan"</strong> to start</li>
            </ol>
            <p className="text-xs text-blue-700 mt-3 italic">
              Note: Scan data is stored in memory and will be lost when the server restarts.
            </p>
          </div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-6 mb-8">
            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-gray-500 text-sm font-medium">Overall Score</h3>
                <Activity className="h-5 w-5 text-blue-500" />
              </div>
              <div className="flex items-baseline">
                <span className="text-3xl font-bold text-gray-900">{stats.overallScore}%</span>
                {scanHistory.length > 1 && (
                  <span className="ml-2 text-sm text-green-600">
                    {stats.overallScore >= 80 ? '✓ Good' : stats.overallScore >= 60 ? '⚠ Fair' : '✗ Needs improvement'}
                  </span>
                )}
              </div>
            </div>

            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-gray-500 text-sm font-medium">Passing Checks</h3>
                <CheckCircle2 className="h-5 w-5 text-green-500" />
              </div>
              <div className="flex items-baseline">
                <span className="text-3xl font-bold text-gray-900">{stats.passedChecks}</span>
                <span className="ml-2 text-sm text-gray-500">/ {stats.totalChecks} checked</span>
              </div>
            </div>

            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-gray-500 text-sm font-medium">Critical Failures</h3>
                <ShieldAlert className="h-5 w-5 text-red-500" />
              </div>
              <div className="flex items-baseline">
                <span className="text-3xl font-bold text-gray-900">{stats.failedChecks}</span>
                <span className="ml-2 text-sm text-red-600">
                  {stats.failedChecks > 0 ? 'Needs attention' : 'All good'}
                </span>
              </div>
            </div>

            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-gray-500 text-sm font-medium">Warnings</h3>
                <AlertCircle className="h-5 w-5 text-yellow-500" />
              </div>
              <div className="flex items-baseline">
                <span className="text-3xl font-bold text-gray-900">{stats.warningChecks}</span>
                <span className="ml-2 text-sm text-gray-500">Manual checks</span>
              </div>
            </div>

            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-gray-500 text-sm font-medium">Recently Fixed</h3>
                <Wrench className="h-5 w-5 text-blue-500" />
              </div>
              <div className="flex items-baseline">
                <span className="text-3xl font-bold text-gray-900">{stats.remediatedChecks}</span>
                <span className="ml-2 text-sm text-gray-500">
                  {stats.remediatedChecks > 0 ? 'Remediated' : 'No changes'}
                </span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-4 gap-6">
            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Recent Activity</h3>
              <div className="space-y-4">
                {scanHistory.slice(0, 5).map((scan) => (
                  <div key={scan.id} className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
                    <div className="flex items-center space-x-3">
                      <div className={`w-2 h-2 rounded-full ${scan.status === 'completed' ? 'bg-green-500' :
                        scan.status === 'failed' ? 'bg-red-500' : 'bg-blue-500'
                        }`}></div>
                      <div>
                        <p className="text-sm font-medium text-gray-900">
                          {scan.nodeName ? `Scan on ${scan.nodeName}` : 'Cluster Scan'}
                        </p>
                        <p className="text-xs text-gray-500 flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {formatTimeAgo(scan.timestamp || scan.startTime || scan.endTime || '')}
                        </p>
                      </div>
                    </div>
                    <span className={`px-2 py-1 text-xs font-medium rounded-full ${scan.status === 'completed'
                      ? 'bg-green-100 text-green-800'
                      : scan.status === 'failed'
                        ? 'bg-red-100 text-red-800'
                        : 'bg-blue-100 text-blue-800'
                      }`}>
                      {scan.status === 'completed' ? 'Completed' :
                        scan.status === 'failed' ? 'Failed' : 'Running'}
                    </span>
                  </div>
                ))}
                {scanHistory.length === 0 && (
                  <p className="text-sm text-gray-500 text-center py-4">No recent scans</p>
                )}
              </div>
            </div>

            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Top Failing Checks</h3>
              <div className="space-y-4">
                {topFailing.length > 0 ? (
                  topFailing.map((check: any, idx: number) => (
                    <div key={`${check.scanId || idx}-${check.itemId || check.id}`} className="p-3 bg-red-50 rounded-lg border border-red-100">
                      <div className="flex items-start space-x-3">
                        <ShieldAlert className="h-5 w-5 text-red-600 mt-0.5 flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-red-900">
                            {check.itemId || check.id}: {check.title || 'Unknown check'}
                          </p>
                          <div className="mt-2 flex items-center gap-3 text-xs text-red-700">
                            {check.nodeName && (
                              <span className="flex items-center gap-1">
                                <span className="font-medium">Node:</span> {check.nodeName}
                              </span>
                            )}
                            {check.timestamp && (
                              <span className="flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                {formatTimeAgo(check.timestamp)}
                              </span>
                            )}
                          </div>
                          {check.details && (
                            <p className="text-xs text-red-700 mt-1">{check.details}</p>
                          )}
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-center py-8">
                    <CheckCircle2 className="h-12 w-12 text-green-500 mx-auto mb-2" />
                    <p className="text-sm text-gray-500">No failing checks</p>
                  </div>
                )}
              </div>
            </div>

            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Manual Checks</h3>
              <div className="space-y-4">
                {manualChecks.length > 0 ? (
                  manualChecks.map((check: any, idx: number) => (
                    <div key={`${check.scanId || idx}-${check.itemId || check.id}`} className="p-3 bg-yellow-50 rounded-lg border border-yellow-100">
                      <div className="flex items-start space-x-3">
                        <AlertCircle className="h-5 w-5 text-yellow-600 mt-0.5 flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-yellow-900">
                            {check.itemId || check.id}: {check.title || 'Unknown check'}
                          </p>
                          <div className="mt-2 flex items-center gap-3 text-xs text-yellow-700">
                            {check.nodeName && (
                              <span className="flex items-center gap-1">
                                <span className="font-medium">Node:</span> {check.nodeName}
                              </span>
                            )}
                            {check.timestamp && (
                              <span className="flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                {formatTimeAgo(check.timestamp)}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-yellow-700 mt-1 flex items-center gap-1">
                            <AlertCircle className="h-3 w-3" />
                            Requires manual review
                          </p>
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-center py-8">
                    <CheckCircle2 className="h-12 w-12 text-green-500 mx-auto mb-2" />
                    <p className="text-sm text-gray-500">No manual checks</p>
                  </div>
                )}
              </div>
            </div>

            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Recently Remediated</h3>
              <div className="space-y-4">
                {remediatedChecks.length > 0 ? (
                  remediatedChecks.map((check: any, idx: number) => (
                    <div key={`${check.scanId || idx}-${check.itemId || check.id}`} className="p-3 bg-green-50 rounded-lg border border-green-100">
                      <div className="flex items-start space-x-3">
                        <Wrench className="h-5 w-5 text-green-600 mt-0.5 flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-green-900">
                            {check.itemId || check.id}: {check.title || 'Unknown check'}
                          </p>
                          <div className="mt-2 flex items-center gap-3 text-xs text-green-700">
                            {check.nodeName && (
                              <span className="flex items-center gap-1">
                                <span className="font-medium">Node:</span> {check.nodeName}
                              </span>
                            )}
                            {check.timestamp && (
                              <span className="flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                {formatTimeAgo(check.timestamp)}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-green-700 mt-1 flex items-center gap-1">
                            <CheckCircle2 className="h-3 w-3" />
                            Fixed and verified
                          </p>
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-center py-8">
                    <AlertCircle className="h-12 w-12 text-gray-400 mx-auto mb-2" />
                    <p className="text-sm text-gray-500">No recent remediations</p>
                    {scanHistory.length < 2 && (
                      <p className="text-xs text-gray-400 mt-1">Compare with previous scan</p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
