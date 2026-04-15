import json

def analyze_bandit_results(json_string):
    """
    Parse Bandit JSON output and return human-readable security report.
    No AI hallucinations - just facts.
    """
    # DEBUG: Show what we received
    print(f"🔍 ANALYZER received: {len(json_string)} chars")
    print(f"🔍 First 500 chars: {json_string[:500]}")
    try:
        data = json.loads(json_string)
    except json.JSONDecodeError as e:
        return f"❌ Error parsing Bandit JSON: {e}"

    # Build the report
    report = []
    report.append("\n" + "="*70)
    report.append("🛡️  SOVERYN SECURITY AUDIT REPORT")
    report.append("="*70)
    report.append("")

    # Get findings FIRST
    findings = data.get('findings', [])

    # Filter out ComfyUI noise
    findings = [f for f in findings if 'ComfyUI' not in f.get('filename', '')]

    # Filter out test files and examples
    findings = [f for f in findings if not any(x in f.get('filename', '') for x in ['test_', 'example', '\\examples\\'])]

    # NOW calculate summary from filtered findings
    high_count = sum(1 for f in findings if f.get('issue_severity') == 'HIGH')
    medium_count = sum(1 for f in findings if f.get('issue_severity') == 'MEDIUM')
    low_count = sum(1 for f in findings if f.get('issue_severity') == 'LOW')

    # Summary
    report.append("📊 SUMMARY:")
    report.append(f"  Total Issues Found: {len(findings)}")
    report.append(f"  🔴 HIGH Severity: {high_count}")
    report.append(f"  🟡 MEDIUM Severity: {medium_count}")
    report.append(f"  🟢 LOW Severity: {low_count}")
    report.append("")

    if not findings:
        report.append("✅ No security issues found!")
        report.append("="*70 + "\n")
        return "\n".join(report)
    
    report.append("="*70)
    report.append("🔍 DETAILED FINDINGS:")
    report.append("="*70)
    report.append("")
    
    # Sort by severity (HIGH -> MEDIUM -> LOW)
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    sorted_findings = sorted(
        findings, 
        key=lambda x: severity_order.get(x.get('issue_severity', 'LOW'), 3)
    )
    
    for i, finding in enumerate(sorted_findings, 1):
        severity = finding.get('issue_severity', 'UNKNOWN')
        severity_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(severity, "⚪")
        
        report.append(f"{severity_emoji} ISSUE #{i}: {severity} SEVERITY")
        report.append(f"  📁 File: {finding.get('filename', 'Unknown')}")
        report.append(f"  📍 Line: {finding.get('line_number', 'Unknown')}")
        report.append(f"  ⚠️  Issue: {finding.get('issue_text', 'No description')}")
        
        cwe = finding.get('issue_cwe', {})
        if cwe:
            report.append(f"  🔗 CWE-{cwe.get('id', '?')}: {cwe.get('link', 'N/A')}")
        
        more_info = finding.get('more_info')
        if more_info:
            report.append(f"  📚 More Info: {more_info}")
        
        # Add fix recommendations for common issues
        fix = get_fix_recommendation(finding)
        if fix:
            report.append(f"  🔧 Fix: {fix}")
        
        report.append("")
    
    report.append("="*70)
    report.append("")
    
    return "\n".join(report)


def get_fix_recommendation(finding):
    """Return fix recommendations for common Bandit findings"""
    test_id = finding.get('test_id', '')
    line_num = finding.get('line_number', 0)
    
    fixes = {
        'B201': f"Change line {line_num}: Set debug=False in production",
        'B104': f"Line {line_num}: Consider binding to '127.0.0.1' instead of '0.0.0.0'",
        'B113': f"Line {line_num}: Add timeout parameter (e.g., timeout=30)",
        'B311': "Use secrets.SystemRandom() for security-critical random values",
        'B303': "Use hashlib with usedforsecurity=False or switch to SHA-256",
        'B608': f"Line {line_num}: Remove shell=True and use list-based arguments",
    }
    
    return fixes.get(test_id)