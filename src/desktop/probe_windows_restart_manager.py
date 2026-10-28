"""Opt-in real Windows API probe using only self-created invisible GUI fixtures.

Does not discover, close, or launch Codex. Run with PYTHONPATH=src on Windows.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

import psutil

from desktop.windows_restart_manager import shutdown


SOURCE = r'''
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
class Fixture : Form {
    string log; bool veto; Timer timer;
    protected override bool ShowWithoutActivation { get { return true; } }
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern int RegisterApplicationRestart(string command, int flags);
    Fixture(string file, bool reject) {
        log = file; veto = reject; Text = "Codex Hybrid isolated shutdown fixture";
        Application.ApplicationExit += delegate { File.AppendAllText(log, "application-exit\n"); };
        AppDomain.CurrentDomain.ProcessExit += delegate { File.AppendAllText(log, "process-exit\n"); };
        Microsoft.Win32.SystemEvents.SessionEnding += delegate(object sender, Microsoft.Win32.SessionEndingEventArgs e) {
            File.AppendAllText(log, "system-query:foreground=" + (GetForegroundWindow() == Handle) + "\n");
            e.Cancel = veto;
        };
        Microsoft.Win32.SystemEvents.SessionEnded += delegate { File.AppendAllText(log, "system-end\n"); };
        ShowInTaskbar = false; Opacity = 0; Width = 1; Height = 1;
        StartPosition = FormStartPosition.Manual; Left = -32000; Top = -32000;
        timer = new Timer(); timer.Interval = 100;
        timer.Tick += delegate { if (File.Exists(log + ".stop")) Application.ExitThread(); };
        timer.Start();
        Shown += delegate { File.AppendAllText(log, "ready\n"); };
    }
    protected override void WndProc(ref Message m) {
        if (m.Msg == 0x10) File.AppendAllText(log, "close\n");
        if (m.Msg == 0x11) {
            File.AppendAllText(log, "query:" + m.LParam.ToInt64() + ":foreground=" + (GetForegroundWindow() == Handle) + "\n");
            m.Result = new IntPtr(veto ? 0 : 1); return;
        }
        if (m.Msg == 0x16) {
            File.AppendAllText(log, "end:" + m.WParam.ToInt64() + ":flags=" + m.LParam.ToInt64() + "\n");
            if (m.WParam != IntPtr.Zero) Application.ExitThread();
            return;
        }
        base.WndProc(ref m);
    }
    [STAThread] static void Main(string[] args) {
        RegisterApplicationRestart(null, 0);
        Application.Run(new Fixture(args[0], args[1] == "veto"));
    }
}
'''


def main():
    if sys.platform != 'win32':
        raise SystemExit('Windows only')
    compiler = Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    with TemporaryDirectory(prefix='codex-hybrid-rm-probe-') as directory:
        directory = Path(directory)
        source, executable = directory/'fixture.cs', directory/'fixture.exe'
        source.write_text(SOURCE, encoding='utf-8')
        subprocess.run([str(compiler), '/nologo', '/target:winexe', '/reference:System.Windows.Forms.dll',
                        '/reference:System.Drawing.dll', '/out:' + str(executable), str(source)],
                       check=True, capture_output=True, timeout=20)
        passed = True
        for mode in ('allow', 'veto'):
            log = directory/(mode + '.log')
            process = subprocess.Popen([str(executable), str(log), mode])
            try:
                deadline = time.monotonic() + 10
                while not log.exists() and time.monotonic() < deadline:
                    time.sleep(0.1)
                if not log.exists():
                    raise RuntimeError('fixture not ready')
                result = shutdown([psutil.Process(process.pid)])
                if mode == 'allow' and result:
                    process.wait(timeout=5)
                alive = process.poll() is None
                events = log.read_text().splitlines()
                print(json.dumps({'fixture': mode, 'shutdown_success': bool(result), 'reason': result.reason,
                                  'still_running': alive, 'exit_code': process.poll(), 'events': events}), flush=True)
                if mode == 'allow':
                    passed = passed and bool(result) and not alive and 'process-exit' in events
                else:
                    passed = passed and not result and alive
                passed = passed and any('foreground=False' in event for event in events)
            finally:
                # Signal only our fixture's private timer to exit. Never kill it.
                log.with_name(log.name + '.stop').touch()
                process.wait(timeout=5)
        assert passed, 'cooperative background shutdown verification failed'


if __name__ == '__main__':
    main()
