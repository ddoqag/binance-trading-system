#!/usr/bin/env python3
"""
Run model training with profitable data generator integration
赚钱版数据生成器与模型训练系统集成脚本
"""

import os
import sys
import logging
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime

# Add project path
sys.path.insert(0, str(Path(__file__).parent))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("RunModelTraining")


def run_qwen_training():
    """
    Run Qwen3.5-7B model training with profitable data generator
    使用赚钱版数据生成器运行 Qwen3.5-7B 模型训练
    """
    logger.info("\n" + "=" * 70)
    logger.info("Running Qwen3.5-7B Model Training")
    logger.info("=" * 70)

    try:
        from prepare_qwen_training_data import main as run_qwen_data_prep
        from qwen_finetune_trainer import main as run_qwen_train

        logger.info("Step 1/2: Preparing Qwen training data...")
        run_qwen_data_prep()

        logger.info("\nStep 2/2: Starting Qwen3.5-7B fine-tuning...")
        run_qwen_train()

        logger.info("\n✅ Qwen3.5-7B training completed successfully!")

        return True

    except Exception as e:
        logger.error(f"\n❌ Qwen training failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False


def run_traditional_model_training():
    """
    Run traditional ML model training with profitable data generator
    使用赚钱版数据生成器运行传统机器学习模型训练
    """
    logger.info("\n" + "=" * 70)
    logger.info("Running Traditional ML Model Training")
    logger.info("=" * 70)

    try:
        from models.model_trainer import ModelTrainer
        from data_generator import BinanceDataLoader

        # Configuration
        data_dir = "data"
        output_dir = "models_output"

        # Load BTCUSDT data (or use custom symbols)
        logger.info("Step 1/3: Loading training data...")
        loader = BinanceDataLoader()

        # Check for existing CSV files in data directory
        import glob
        csv_files = glob.glob(os.path.join(data_dir, "BTCUSDT*.csv"))

        if not csv_files:
            logger.error(f"No BTCUSDT CSV files found in {data_dir}")
            logger.info("Please ensure you have downloaded historical data first")
            return False

        # Load the first available file
        logger.info(f"Using data file: {csv_files[0]}")
        df = loader.load_data_from_csv(csv_files[0])
        logger.info(f"Loaded {len(df)} records")

        # Initialize model trainer
        logger.info("\nStep 2/3: Initializing model trainer...")
        trainer = ModelTrainer(output_dir=output_dir)

        # Prepare training and test data
        logger.info("Step 3/3: Training models...")
        train_df, test_df = trainer.prepare_data(df, train_ratio=0.8, target_horizon=1)

        logger.info(f"Train data: {len(train_df)}, Test data: {len(test_df)}")

        # Train different model types
        model_types = ["random_forest", "xgboost", "lightgbm"]

        for model_type in model_types:
            logger.info(f"\nTraining {model_type}...")

            metrics = trainer.train_model(
                train_df,
                test_df,
                model_type=model_type,
                symbol="BTCUSDT"
            )

            logger.info(f"Results: Accuracy={metrics['accuracy']:.4f}, F1={metrics['f1']:.4f}")

        # Save results
        trainer.save_results()
        logger.info(f"\nTraining results saved to: {output_dir}")

        logger.info("\n✅ Traditional ML model training completed successfully!")

        return True

    except Exception as e:
        logger.error(f"\n❌ Traditional ML training failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False


def run_data_generator_pipeline():
    """
    Run complete profitable data generation and training pipeline
    运行完整的赚钱版数据生成和训练流程
    """
    logger.info("\n" + "=" * 70)
    logger.info("Running Profitable Data Generator Pipeline")
    logger.info("=" * 70)

    try:
        from data_generator import ProfitableDataGenerator, DataSplitStrategy

        # Create and run generator
        logger.info("Step 1/3: Generating profitable data...")
        generator = ProfitableDataGenerator()

        # Configure to use time-based split
        generator.config.train.train_start_date = "2024-01-01"
        generator.config.train.train_end_date = "2024-10-31"
        generator.config.train.val_start_date = "2024-11-01"
        generator.config.train.val_end_date = "2024-11-30"
        generator.config.train.test_start_date = "2024-12-01"
        generator.config.train.test_end_date = "2024-12-31"

        result = generator.generate_training_data(
            base_dir="data",
            symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            split_strategy=DataSplitStrategy.TIME_BASED,
            save_output=True,
            validate_quality=True
        )

        logger.info("\n✅ Data generation completed successfully!")
        generator.print_generation_summary(result)

        # Check if we need to run QLoRA training
        answer = input("\nWould you like to run QLoRA training now? (y/n): ").lower().strip()
        if answer == "y":
            run_qwen_training()

        return True

    except Exception as e:
        logger.error(f"\n❌ Data generation pipeline failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False


def print_menu():
    """Print training options menu"""
    print("\n" + "=" * 70)
    print("Profitable Data Generator - Training Options")
    print("=" * 70)
    print()
    print("Please select training option:")
    print()
    print("1. Run Complete Pipeline (Data Generation + Training)")
    print("2. Run Qwen3.5-7B QLoRA Fine-Tuning")
    print("3. Run Traditional ML Model Training")
    print("4. Generate Data Only")
    print()
    print("0. Exit")
    print()


def main():
    """Main training interface"""
    while True:
        print_menu()
        choice = input("Enter your choice: ").strip()

        if choice == "0":
            logger.info("\nExiting training system. Goodbye!")
            break

        elif choice == "1":
            run_data_generator_pipeline()

        elif choice == "2":
            run_qwen_training()

        elif choice == "3":
            run_traditional_model_training()

        elif choice == "4":
            from data_generator import ProfitableDataGenerator, DataSplitStrategy
            generator = ProfitableDataGenerator()
            generator.generate_training_data()

        else:
            logger.warning("Invalid choice. Please enter a number between 0 and 4.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nUser interrupted. Exiting...")
    except Exception as e:
        logger.error(f"\nError: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
