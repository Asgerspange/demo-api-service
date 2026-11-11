"""Main application entry point for the demo processor."""
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from config import AppConfig
from demo_service import DemoService

async def main():
    # Load configuration
    config = AppConfig.from_env()
    
    # Initialize the demo service
    demo_service = DemoService(config)
    
    # Check if we're in debug mode
    if config.debug.enabled:
        logger.info("Running in debug mode - processing single demo file")
        demo_id = await demo_service.process_debug_demo()
        if demo_id:
            logger.info(f"Debug demo processing completed. Demo ID: {demo_id}")
        else:
            logger.error("Debug demo processing failed")
        
        # Wait for background tasks (post-processing) to complete before closing loop
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if tasks:
            logger.info(f"Waiting for {len(tasks)} background task(s) to complete...")
            await asyncio.gather(*tasks, return_exceptions=True)
        
        return

    # Production mode - start scheduler
    scheduler = AsyncIOScheduler()
    
    # Process pending demos every 10 seconds
    scheduler.add_job(
        demo_service.check_and_process_demos,
        "interval",
        seconds=10,
        kwargs={"scheduler": scheduler},
        max_instances=1,
    )
    
    # Clean up orphaned chunks every hour
    scheduler.add_job(
        demo_service.cleanup_chunks,
        "interval",
        hours=1,
        max_instances=1,
    )

    logger.info("CSStrats demo processor service started")
    scheduler.start()

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down demo processor...")
        scheduler.shutdown()

if __name__ == "__main__":
    asyncio.run(main())