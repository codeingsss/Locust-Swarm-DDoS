import os
import discord
from discord import app_commands
from discord.ext import commands
from github import Github
from dotenv import load_dotenv
import asyncio
import time

load_dotenv()
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
PAT_TOKEN     = os.environ["PAT_TOKEN"]
REPO_OWNER    = os.environ["REPO_OWNER"]
REPO_NAME     = os.environ["REPO_NAME"]
WORKFLOW_FILE = os.environ["WORKFLOW_FILE"]
REF           = os.environ.get("REF", "main")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

gh = Github(PAT_TOKEN)
repo = gh.get_repo(f"{REPO_OWNER}/{REPO_NAME}")

# ============================================================
# 작업 ID를 추적하기 위한 전역 변수
# ============================================================
active_tests = {}  # {interaction_id: {"workflow_id": "...", "start_time": 0, "target": ""}}

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")
    print(f"📦 Connected to repository: {REPO_OWNER}/{REPO_NAME}")

# ============================================================
# 핵심 함수: 워크플로우 디스패치 + 상태 모니터링
# ============================================================
async def dispatch_locust_workflow(url: str, users: int, spawn_rate: int, workers: int, run_time: str):
    workflow = repo.get_workflow(WORKFLOW_FILE)
    workflow.create_dispatch(
        ref=REF,
        inputs={
            "HOST": url,
            "USERS": str(users),
            "SPAWN_RATE": str(spawn_rate),
            "WORKERS": str(workers),
            "RUN_TIME": run_time
        }
    )

async def monitor_workflow(interaction: discord.Interaction, workflow_id: str, start_time: float):
    """
    워크플로우 상태를 모니터링하여 종료 시 완료 메시지 전송
    """
    await asyncio.sleep(5)  # 초기 실행 대기
    
    try:
        workflow = repo.get_workflow(WORKFLOW_FILE)
        runs = workflow.get_runs()
        
        # 가장 최근 실행 중인 워크플로우 찾기
        for run in runs:
            if run.id == int(workflow_id) or run.status == "in_progress":
                # 실행 중 상태 모니터링
                while run.status in ["queued", "in_progress"]:
                    await asyncio.sleep(10)
                    run = repo.get_workflow_run(run.id)
                    
                    # 중간 상태 업데이트 (선택사항)
                    if run.status == "in_progress":
                        # 30초마다 진행 상황 알림
                        elapsed = int(time.time() - start_time)
                        if elapsed % 30 == 0 and elapsed > 0:
                            await interaction.channel.send(
                                f"⏳ 테스트 진행 중... ({elapsed}초 경과)"
                            )
                
                # 완료 또는 실패 처리
                if run.status == "completed":
                    conclusion = run.conclusion
                    elapsed = int(time.time() - start_time)
                    
                    if conclusion == "success":
                        embed = discord.Embed(
                            title="✅ 스트레스 테스트 완료!",
                            color=discord.Color.green(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.add_field(name="대상 URL", value=f"`{active_tests.get(interaction.id, {}).get('target', 'N/A')}`", inline=False)
                        embed.add_field(name="실행 시간", value=f"{elapsed}초", inline=True)
                        embed.add_field(name="워크플로우 ID", value=f"`{run.id}`", inline=True)
                        embed.add_field(name="결과", value="✅ 성공", inline=True)
                        embed.set_footer(text="GitHub Actions 로그에서 자세한 내용을 확인하세요")
                        
                        await interaction.channel.send(embed=embed)
                    else:
                        embed = discord.Embed(
                            title="❌ 테스트 실패",
                            color=discord.Color.red(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.add_field(name="결과", value=f"`{conclusion}`", inline=False)
                        embed.add_field(name="워크플로우 ID", value=f"`{run.id}`", inline=True)
                        embed.set_footer(text="GitHub Actions 로그를 확인하여 오류를 분석하세요")
                        
                        await interaction.channel.send(embed=embed)
                
                break
                
    except Exception as e:
        await interaction.channel.send(f"⚠️ 워크플로우 모니터링 중 오류 발생: `{e}`")

# ============================================================
# 트리 명령어 (공격 시작)
# ============================================================
@bot.tree.command(name="stress", description="🎯 분산 스트레스 테스트 시작")
@app_commands.describe(
    url="테스트할 대상 URL (예: https://example.com)",
    users="전체 가상 사용자 수",
    spawn_rate="초당 생성할 사용자 수",
    workers="워커 프로세스 수",
    run_time="실행 시간 (예: 5m, 1h, 30s)"
)
@app_commands.checks.has_permissions(administrator=True)
async def stress(interaction: discord.Interaction, 
                 url: str, 
                 users: int, 
                 spawn_rate: int, 
                 workers: int, 
                 run_time: str):
    
    # 권한 확인
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ 이 명령어는 관리자 권한이 필요합니다.", 
            ephemeral=True
        )
        return
    
    await interaction.response.defer(thinking=True)
    
    try:
        # 워크플로우 디스패치
        await dispatch_locust_workflow(url, users, spawn_rate, workers, run_time)
        
        # 시작 메시지 (Embed)
        embed = discord.Embed(
            title="🚀 스트레스 테스트 시작!",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="🎯 대상 URL", value=f"`{url}`", inline=False)
        embed.add_field(name="👥 가상 사용자", value=f"`{users:,}`명", inline=True)
        embed.add_field(name="⚡ 생성 속도", value=f"`{spawn_rate}`명/초", inline=True)
        embed.add_field(name="🖥️ 워커 수", value=f"`{workers}`개", inline=True)
        embed.add_field(name="⏱️ 실행 시간", value=f"`{run_time}`", inline=True)
        embed.add_field(name="📊 상태", value="🟢 실행 중...", inline=True)
        embed.set_footer(text=f"요청자: {interaction.user.display_name}")
        
        await interaction.followup.send(embed=embed)
        
        # 작업 기록 저장
        active_tests[interaction.id] = {
            "target": url,
            "start_time": time.time()
        }
        
        # 백그라운드에서 워크플로우 모니터링 시작
        await monitor_workflow(interaction, "latest", time.time())
        
    except Exception as e:
        await interaction.followup.send(f"❌ 워크플로우 디스패치 실패: `{e}`", ephemeral=True)

# ============================================================
# 트리 명령어 (공격 종료 - 강제 중지)
# ============================================================
@bot.tree.command(name="stress_stop", description="🛑 실행 중인 스트레스 테스트 중지")
@app_commands.checks.has_permissions(administrator=True)
async def stress_stop(interaction: discord.Interaction):
    
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ 이 명령어는 관리자 권한이 필요합니다.", 
            ephemeral=True
        )
        return
    
    await interaction.response.defer(thinking=True)
    
    try:
        workflow = repo.get_workflow(WORKFLOW_FILE)
        runs = workflow.get_runs()
        
        stopped_count = 0
        for run in runs:
            if run.status in ["queued", "in_progress"]:
                run.cancel()
                stopped_count += 1
                
                # 종료 메시지 전송
                embed = discord.Embed(
                    title="🛑 테스트 강제 중지됨",
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="중지된 워크플로우", value=f"`{run.id}`", inline=True)
                embed.add_field(name="상태", value=f"`{run.status}` → `cancelled`", inline=True)
                embed.set_footer(text=f"요청자: {interaction.user.display_name}")
                
                await interaction.followup.send(embed=embed)
                return
        
        if stopped_count == 0:
            await interaction.followup.send("ℹ️ 현재 실행 중인 테스트가 없습니다.")
            
    except Exception as e:
        await interaction.followup.send(f"❌ 중지 실패: `{e}`", ephemeral=True)

# ============================================================
# 트리 명령어 (현황 조회)
# ============================================================
@bot.tree.command(name="stress_status", description="📊 현재 테스트 상태 확인")
@app_commands.checks.has_permissions(administrator=True)
async def stress_status(interaction: discord.Interaction):
    
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ 이 명령어는 관리자 권한이 필요합니다.", 
            ephemeral=True
        )
        return
    
    await interaction.response.defer(thinking=True)
    
    try:
        workflow = repo.get_workflow(WORKFLOW_FILE)
        runs = workflow.get_runs()
        
        embed = discord.Embed(
            title="📊 테스트 현황",
            color=discord.Color.purple(),
            timestamp=discord.utils.utcnow()
        )
        
        found = False
        for run in runs:
            if run.status in ["queued", "in_progress"]:
                found = True
                embed.add_field(
                    name=f"🟢 실행 중 (ID: {run.id})",
                    value=f"• 상태: `{run.status}`\n• 시작: <t:{int(run.created_at.timestamp())}:R>",
                    inline=False
                )
                break
        
        if not found:
            embed.add_field(name="ℹ️ 현재 실행 중인 테스트 없음", value="대기 중...", inline=False)
        
        embed.set_footer(text=f"요청자: {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(f"❌ 상태 확인 실패: `{e}`", ephemeral=True)

# ============================================================
# 에러 핸들러
# ============================================================
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message(
            "❌ 이 명령어를 실행할 권한이 없습니다.", 
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"⚠️ 오류 발생: `{error}`", 
            ephemeral=True
        )

# ============================================================
# 봇 실행
# ============================================================
bot.run(DISCORD_TOKEN)
