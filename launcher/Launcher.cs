// Stable Windows entry point. Bot versions are read from the project at runtime.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: AssemblyTitle("ZhBot Launcher")]
[assembly: AssemblyDescription("Local launcher for the configured ZhBot project")]
[assembly: AssemblyVersion("1.0.0.0")]

internal static class Program
{
    internal static readonly string Root = AppDomain.CurrentDomain.BaseDirectory;
    internal static readonly string Python = Path.Combine(Root, ".venv", "Scripts", "python.exe");
    internal static readonly string Bridge = Path.Combine(Root, "launcher", "control.py");

    internal static string Call(string action)
    {
        if (!File.Exists(Python) || !File.Exists(Bridge))
            throw new IOException("请将 ZhBot.exe 保留在完整项目根目录。缺少 .venv Python 或 launcher/control.py；安装步骤见 README。");
        var info = new ProcessStartInfo(Python, "\"" + Bridge + "\" " + action);
        info.WorkingDirectory = Root;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        info.StandardOutputEncoding = Encoding.UTF8;
        info.StandardErrorEncoding = Encoding.UTF8;
        info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        var output = new StringBuilder();
        var errors = new StringBuilder();
        using (var process = new Process())
        {
            process.StartInfo = info;
            process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) lock(output) output.AppendLine(e.Data); };
            process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) lock(errors) errors.AppendLine(e.Data); };
            process.Start();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            if (!process.WaitForExit(15000))
            {
                // Only the short-lived control helper is terminated on timeout.
                process.Kill();
                throw new IOException("读取本机控制结果超时。机器人进程未被强制停止，请刷新状态。");
            }
            process.WaitForExit();
            if (output.Length == 0)
                throw new IOException(errors.Length == 0 ? "控制入口没有返回状态。" : errors.ToString());
            return output.ToString();
        }
    }

    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length == 1 && args[0] == "--check")
        {
            // Read-only smoke check for the EXE-to-Python chain; no injection.
            try
            {
                string result = Call("check");
                Directory.CreateDirectory(Path.Combine(Root, "runtime"));
                File.WriteAllText(Path.Combine(Root, "runtime", "launcher-check.json"), result, new UTF8Encoding(false));
                var record = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(result);
                return Convert.ToString(record["state"]) == "CHECKED" ? 0 : 1;
            }
            catch (Exception error)
            {
                MessageBox.Show(error.Message, "ZhBot 入口检查失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new LauncherForm(args.Length == 1 && args[0] == "--status-only"));
        return 0;
    }
}

internal sealed class LauncherForm : Form
{
    private readonly Label headline = new Label();
    private readonly TextBox details = new TextBox();
    private readonly Button start = new Button();
    private readonly Button stop = new Button();
    private readonly Button refresh = new Button();
    private readonly Timer timer = new Timer();
    private bool busy;
    private string startupLog = "";

    internal LauncherForm(bool statusOnly)
    {
        Text = "ZhBot 机器人";
        Font = new Font("Microsoft YaHei UI", 10);
        ClientSize = new Size(720, 465);
        MinimumSize = new Size(600, 420);
        StartPosition = FormStartPosition.CenterScreen;
        headline.SetBounds(22, 20, 670, 35);
        headline.Font = new Font(Font.FontFamily, 15, FontStyle.Bold);
        headline.Text = "正在检查…";
        headline.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        details.SetBounds(22, 72, 676, 270);
        details.Multiline = true;
        details.ReadOnly = true;
        details.ScrollBars = ScrollBars.Vertical;
        details.BackColor = SystemColors.Window;
        details.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Bottom;
        start.Text = "启动";
        stop.Text = "正常停止";
        refresh.Text = "刷新状态";
        start.SetBounds(22, 358, 105, 36);
        stop.SetBounds(141, 358, 115, 36);
        refresh.SetBounds(270, 358, 115, 36);
        foreach (var button in new[] { start, stop, refresh }) button.Anchor = AnchorStyles.Left | AnchorStyles.Bottom;
        var note = new Label();
        note.SetBounds(22, 409, 676, 46);
        note.Anchor = AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Bottom;
        note.Text = "关闭此窗口后机器人继续在后台运行。需要结束收发时，点击“正常停止”。\r\n更新项目后继续使用这个入口；微信扫码或手机确认由本人完成。";
        Controls.AddRange(new Control[] { headline, details, start, stop, refresh, note });
        start.Click += delegate { Execute("start"); };
        stop.Click += delegate { Execute("stop"); };
        refresh.Click += delegate { Execute("status"); };
        timer.Interval = 3000;
        timer.Tick += delegate { Execute("status"); };
        Shown += delegate { Execute(statusOnly ? "status" : "start"); timer.Start(); };
        FormClosed += delegate { timer.Stop(); timer.Dispose(); };
    }

    private static string Value(Dictionary<string, object> record, string key)
    {
        object value;
        return record.TryGetValue(key, out value) ? Convert.ToString(value) : "";
    }

    private void Execute(string action)
    {
        if (busy || IsDisposed) return;
        busy = true;
        start.Enabled = stop.Enabled = refresh.Enabled = false;
        var worker = new BackgroundWorker();
        worker.DoWork += delegate(object sender, DoWorkEventArgs args) { args.Result = Program.Call(action); };
        worker.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs args)
        {
            worker.Dispose();
            if (IsDisposed) return;
            busy = false;
            start.Enabled = stop.Enabled = refresh.Enabled = true;
            if (args.Error != null)
            {
                headline.Text = "入口错误";
                details.Text = args.Error.Message;
                return;
            }
            try
            {
                var record = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>((string)args.Result);
                string state = Value(record, "state");
                if (Value(record, "stderr_log") != "") startupLog = Value(record, "stderr_log");
                string meaning;
                switch (state)
                {
                    case "READY": meaning = "已连接，机器人运行中"; break;
                    case "STARTING": meaning = "正在启动…"; break;
                    case "STOPPED": meaning = "机器人已停止"; break;
                    case "STOP_REQUESTED": meaning = "正在正常停止…"; break;
                    case "LOGIN_REQUIRED": meaning = "请登录已绑定的机器人微信，再点击启动"; break;
                    case "VERSION_UNSUPPORTED": meaning = "微信构建尚不受支持"; break;
                    case "RECONNECTING": meaning = "正在重新连接"; break;
                    case "STALE": meaning = "状态待核验"; break;
                    default: meaning = "需要检查运行状态"; break;
                }
                headline.Text = meaning;
                var lines = new StringBuilder();
                lines.AppendLine("状态：" + state + "    版本：v" + Value(record, "version"));
                if (Value(record, "pid") != "") lines.AppendLine("机器人进程：" + Value(record, "pid"));
                if (Value(record, "launcher_pid") != "") lines.AppendLine("启动进程：" + Value(record, "launcher_pid"));
                foreach (string key in new[] { "reason", "error", "launcher_note" })
                    if (Value(record, key) != "") lines.AppendLine(Value(record, key));
                if (state == "STOPPED" && Value(record, "recorded_state") != "")
                    lines.AppendLine("退出时状态：" + Value(record, "recorded_state"));
                object counts;
                if (record.TryGetValue("counts", out counts))
                    lines.AppendLine("队列：" + new JavaScriptSerializer().Serialize(counts));
                if (Value(record, "data_dir") != "") lines.AppendLine("数据目录：" + Value(record, "data_dir"));
                lines.AppendLine("项目目录：" + Program.Root);
                if (startupLog != "")
                {
                    lines.AppendLine("本次启动错误日志：" + startupLog);
                    if (state == "STOPPED" && File.Exists(startupLog))
                    {
                        // Bounded local diagnostic; logs themselves stay in runtime.
                        using (var stream = new FileStream(startupLog, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                        using (var reader = new StreamReader(stream, Encoding.UTF8))
                        {
                            char[] tail = new char[3000];
                            int length = reader.Read(tail, 0, tail.Length);
                            if (length > 0) lines.AppendLine(new string(tail, 0, length));
                        }
                    }
                }
                details.Text = lines.ToString();
                if (Value(record, "process_alive") == "True" || state == "STARTING") start.Enabled = false;
                stop.Enabled = state != "STOPPED" && state != "STOP_REQUESTED" && state != "ERROR";
            }
            catch (Exception error)
            {
                headline.Text = "无法读取状态";
                details.Text = error.Message;
            }
        };
        worker.RunWorkerAsync();
    }
}
